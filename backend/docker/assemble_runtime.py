"""Assemble reviewed Debian runtime additions for the same-release distroless base.

The complete maintained base is retained. Copy missing shared-library packages,
their copyright and dpkg metadata; never delete metadata to alter scan results.
ldconfig is needed by CPython 3.11 ctypes.util.find_library; no shell is required.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sysconfig

BASE = Path("/runtime-base")
OUT = Path("/runtime-overlay")
ALLOWED = {
    "libbz2-1.0", "libcrypt1", "libdb5.3t64", "libexpat1", "libffi8", "libgdbm6t64", "libgdbm-compat4t64",
    "liblzma5", "libncursesw6", "libreadline8t64", "libsqlite3-0", "libtinfo6", "libuuid1",
}


def command(*args, env=None):
    return subprocess.check_output(args, text=True, env=env)


def copy_file(source):
    source = Path(source)
    target = OUT / str(source).lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        target.symlink_to(source.readlink())
    else:
        shutil.copy2(source, target)


def record_package(package, files, partial=False):
    status = command("dpkg-query", "-s", package)
    name = re.search(r"^Package: (.+)$", status, re.M).group(1)
    metadata = OUT / "var/lib/dpkg/status.d"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / name).write_text(status)
    # Only claim checksums for files actually included in the runtime overlay.
    sums = []
    for path in files:
        source = Path(path)
        if source.is_file() and not source.is_symlink():
            sums.append(hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest() + "  " + path.lstrip("/"))
    (metadata / (name + ".md5sums")).write_text("\n".join(sums) + "\n")
    return {"package": name, "version": re.search(r"^Version: (.+)$", status, re.M).group(1),
        "partial_package": partial, "files": sorted(files)}


def main():
    OUT.mkdir()
    dependencies = set()
    # Check every installed ELF extension, including bundled native ML libraries.
    targets = [Path("/usr/local/bin/python3.11")]
    targets += [p for p in Path("/usr/local/lib").rglob("*")
        if p.is_file() and ".so" in p.name and p.open("rb").read(4) == b"\x7fELF"]
    # Wheel-private libraries can rely on a parent's RPATH when imported. Supply
    # their directories only for standalone ldd analysis; runtime imports/ML tests
    # verify the wheels' actual loader behavior without this build-only setting.
    library_dirs = sorted({str(path.parent) for path in targets})
    linker_env = dict(os.environ, LD_LIBRARY_PATH=":".join(library_dirs))
    optional_unavailable = []
    for target in targets:
        output = command("ldd", str(target), env=linker_env)
        if "not found" in output:
            missing = set(re.findall(r"(\S+)\s+=>\s+not found", output))
            if (str(target.parent).endswith("/numba/np/ufunc")
                    and target.name.startswith("tbbpool.") and missing == {"libtbb.so.12"}):
                # TBB is an uninstalled optional Numba backend in the baseline.
                # Keep its module and normal OpenMP/workqueue fallback, not a new dependency.
                optional_unavailable.append({"module": str(target), "missing": sorted(missing)})
            else:
                raise RuntimeError("Unresolved native library: " + str(target))
        dependencies.update(re.findall(r"(?:=>\s+)?(/[^\s()]+)", output))
    packages = set()
    for path in sorted(dependencies):
        if path.startswith("/usr/local/") or (BASE / path.lstrip("/")).exists():
            continue
        resolved = Path(path).resolve()
        owner = command("dpkg-query", "-S", str(resolved)).split(": ", 1)[0]
        name = owner.split(":", 1)[0]
        if name not in ALLOWED:
            raise RuntimeError("Unreviewed additional runtime package: " + name)
        packages.add(owner)
    inventory = []
    for package in sorted(packages):
        files = [p for p in command("dpkg-query", "-L", package).splitlines()
            if Path(p).is_file() or Path(p).is_symlink()]
        for path in files:
            copy_file(path)
        inventory.append(record_package(package, files))
    # Keep only the required libc-bin executable, plus attribution and conservative
    # source-package metadata. No ldd shell script or administrative tools copied.
    ldconfig = Path("/sbin/ldconfig").resolve()
    files = [str(ldconfig), "/usr/share/doc/libc-bin/copyright"]
    for path in files:
        copy_file(path)
    inventory.append(record_package("libc-bin", files, partial=True))
    # Distroless has usr-merged directories; provide the conventional executable
    # path explicitly if the maintained base does not already have /sbin.
    if not (BASE / "sbin").exists() and not (BASE / "sbin").is_symlink():
        (OUT / "sbin").symlink_to("usr/sbin")
    assembled = Path("/ldconfig-root")
    shutil.copytree(BASE, assembled, symlinks=True)
    shutil.copytree(OUT, assembled, symlinks=True, dirs_exist_ok=True)
    library = assembled / "usr/local/lib"
    library.mkdir(parents=True, exist_ok=True)
    for path in Path("/usr/local/lib").glob("libpython3.11.so*"):
        shutil.copy2(path, library / path.name, follow_symlinks=False)
    triplet = sysconfig.get_config_var("MULTIARCH")
    conf = f"/usr/local/lib\n/lib/{triplet}\n/usr/lib/{triplet}\n"
    (assembled / "etc/ld.so.conf").write_text(conf)
    subprocess.run([str(ldconfig), "-r", str(assembled)], check=True)
    (OUT / "etc").mkdir(exist_ok=True)
    shutil.copy2(assembled / "etc/ld.so.cache", OUT / "etc/ld.so.cache")
    (OUT / "etc/ld.so.conf").write_text(conf)
    for filename, entry in (
        ("passwd", "appuser:x:10001:10001:PropPulse:/home/appuser:/sbin/nologin\n"),
        ("group", "appuser:x:10001:\n")):
        (OUT / "etc" / filename).write_text((BASE / "etc" / filename).read_text() + entry)
    data = OUT / "app/data"
    data.mkdir(parents=True)
    os.chown(data, 10001, 10001)
    manifest = OUT / "usr/share/proppulse/runtime-components.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    (manifest.parent / "optional-libraries.json").write_text(json.dumps(optional_unavailable, indent=2) + "\n")


if __name__ == "__main__":
    main()
