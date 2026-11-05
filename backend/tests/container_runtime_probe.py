"""Additional native/standard-library checks for the minimal production image.

Mount beside production_image_probe.py; use --network none and private dummy
production settings. No database connection, provider, or application lifespan.
"""
import bz2
import contextlib
import ctypes
import ctypes.util
import dbm
import gzip
import importlib
import io
import json
import lzma
import os
from pathlib import Path
import pwd
import socket
import sqlite3
import ssl
import tempfile
from zoneinfo import ZoneInfo

import production_image_probe


def main():
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        production_image_probe.run()
    result = json.loads(captured.getvalue())
    assert pwd.getpwuid(10001).pw_name == "appuser"
    imported = []
    for file in Path("/usr/local/lib/python3.11/lib-dynload").glob("*.so"):
        name = file.name.split(".", 1)[0]
        importlib.import_module(name)
        imported.append(name)
    found = {}
    for name in ("c", "m", "ssl", "ffi", "gomp", "sqlite3", "bz2", "lzma", "readline", "uuid"):
        value = ctypes.util.find_library(name)
        assert value, name
        ctypes.CDLL(value)
        found[name] = value
    assert len(ssl.create_default_context().get_ca_certs()) > 100
    assert socket.getaddrinfo("localhost", 8000)
    assert ZoneInfo("America/Toronto") and ZoneInfo("America/New_York")
    data = b"PropPulse isolated runtime roundtrip" * 100
    for module in (gzip, bz2, lzma):
        assert module.decompress(module.compress(data)) == data
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    with tempfile.TemporaryDirectory() as directory:
        with dbm.open(str(Path(directory) / "probe"), "c") as database:
            database[b"probe"] = data
            assert database[b"probe"] == data
    import numba
    import numpy as np
    numba.set_num_threads(2)
    @numba.njit(parallel=True)
    def sum_values(values):
        total = 0.0
        for index in numba.prange(len(values)):
            total += values[index]
        return total
    assert sum_values(np.arange(100.0)) == 4950.0
    # Actual component absence, independent of scanner source-package attribution.
    absent = ["/bin/sh", "/bin/bash", "/usr/bin/apt", "/usr/bin/dpkg", "/usr/bin/perl",
        "/usr/bin/mount", "/usr/bin/nsenter", "/usr/bin/infocmp", "/usr/lib/systemd/systemd-homed"]
    assert not any(Path(path).exists() for path in absent)
    manifest = json.loads(Path("/usr/share/proppulse/runtime-components.json").read_text())
    for entry in manifest:
        assert Path("/var/lib/dpkg/status.d", entry["package"]).is_file()
        assert all(Path(path).exists() for path in entry["files"])
    for root in ("/usr", "/app"):
        for directory, _, files in os.walk(root):
            for name in files:
                path = Path(directory) / name
                if path.is_file() and not path.is_symlink():
                    assert not path.stat().st_mode & 0o6000, str(path)
    packages = {}
    for path in Path("/var/lib/dpkg/status.d").iterdir():
        if path.name.endswith((".md5sums", ".list")):
            continue
        fields = dict(line.split(": ", 1) for line in path.read_text().splitlines() if ": " in line and not line.startswith(" "))
        if "Package" in fields:
            packages[fields["Package"]] = fields["Version"]
    result.update(stdlib_extensions=sorted(imported), ctypes_libraries=found,
        ca_roots_loaded=True, timezone_data=True, compression_sqlite_dbm=True,
        administrative_binaries_absent=absent, runtime_package_metadata=True,
        numba_parallel_backend=numba.threading_layer(), setuid_setgid_files=0,
        os_packages=packages)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
