# Container image remediation

October 24, 2026. Local Linux/amd64 verification from HEAD `d4ed12cada04163fa8cb78b4ec8ddcf39bfe6c46` plus these uncommitted changes. No public deployment, provider requests, development PostgreSQL access/migration, dependency upgrades, commit or push. The seven protected files retain their starting SHA-256 hashes.

## Decision and measured comparison

Use the signed, digest-pinned Debian 13 distroless C/C++ base with official **CPython 3.11.17**, the unchanged Python lock and reviewed runtime-library additions. This removes unneeded administrative tools without replacing glibc or changing Python's minor version. Use the official **PostgreSQL 15.19** image derivative with `gosu` physically removed from the effective runtime filesystem and default **UID70** enforced. No substitute privileged binary is installed.

All rows below are actual rebuilt/scanned images using the same database. Counts are advisory **rows / distinct IDs**, not independent exploits. C/H means critical/high rows; no severity filter or advisory suppression was used.

| Candidate | OS | Size GB | OS rows / IDs | Go rows / IDs | C/H rows | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Stage 3 backend, refreshed scan | Debian 13.7 | 1.893 | 166 / 71 | 0 | 0 / 44 | Baseline |
| Latest official 3.11 slim/trixie rebuild | Debian 13.7 | 1.893 | 166 / 71 | 0 | 0 / 44 | Native/lock/password/JWT passed; current base digest unchanged, no security reduction |
| Official 3.11 slim/bookworm comparison | Debian 12.15 | 1.883 | 286 / 124 | 0 | 2 / 61 | Native probe passed; older base adds findings, not selected |
| **Selected minimal backend** | Debian 13.7 | **1.770** | **67 / 38** | 0 | **0 / 6** | Full runtime/database checks passed |
| Official PostgreSQL 15.19 | Alpine 3.24.3 | 0.416 | 0 / 0 | 61 / 61 | 1 / 25 | Helper still installed; direct-UID startup avoids execution |
| **Selected non-root PostgreSQL derivative** | Alpine 3.24.3 | **0.416** | **0 / 0** | **0 / 0** | **0 / 0** | Helper absent; fresh init/atomic restore passed |

Backend OS rows fell **166 to 67**, distinct IDs **71 to 38**, high rows **44 to 6**, and installed OS packages **88 to 26**. Final backend severity rows: **6 high, 40 medium, 21 low; zero critical/unknown**. The final backend retains zero Python findings and 62 installed Python distributions. The gateway is unchanged; its earlier Stage 3 scan is historical evidence, not a new scan claim.

The bookworm critical rows require context: Debian says [CVE-2023-45853](https://security-tracker.debian.org/tracker/CVE-2023-45853) is in MiniZip code not built into the affected bookworm zlib binaries. [CVE-2025-7458](https://security-tracker.debian.org/tracker/CVE-2025-7458) remains in bookworm SQLite and requires crafted SQL; trixie's SQLite is fixed. Raw scanner counts are retained rather than silently suppressed, and neither row establishes an exposed PropPulse exploit.

## Immutable images and scan evidence

Selected local OCI index digests:

- Backend `proppulse-backend:hardened`: `sha256:4d8987247ab7412afa0a888d691151aeb4f76cba1ff1ed978fef5516eeaaf8af`.
- PostgreSQL `proppulse-postgres:nonroot`: `sha256:b912b075d40dcd340143b97a39e2db77a32aaa58e091394e7e6156a409985a8f`.

Pinned registry inputs (also rechecked against current registry tags after testing):

- Official Python 3.11 builder: `python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377`.
- Maintained runtime: `gcr.io/distroless/cc-debian13:nonroot@sha256:3ee00291cf386ec52a552e6a858d555debd74776eb4bfa53fa3df2cd6677515e`.
- Official PostgreSQL parent: `postgres:15-alpine@sha256:a8e042598834300dfaa17a54f695b87b7f25d3490433bbbe2ef3bffbb9747f24`.
- Bookworm input: `python:3.11-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf`.

Comparison output digests: trixie `sha256:3694dd67f0fb9e7867981a2aebcb24f790ad05c38cc82c66a51132cd5faa3cba`; bookworm `sha256:36b79806254e8ec8663624e330e2d73641f19b6c956c137a361c6b13ed51f6aa`. Original Stage 3 backend digest remains `sha256:af7fa6592e37a7bde72eda49f735dee9f797dd3319cda233e192bc30fe4e0a76`.

**Trivy 0.76.1**, database updated **2026-10-24T13:07:23Z**, freshly downloaded **19:27:37Z**. Final backend and official-parent scans completed **19:49:43Z / 19:49:46Z**; derivative PostgreSQL scan completed **19:35:04Z**. All used that same database. Final exact resolved Python graph: **pip-audit 2.10.1, zero findings**. No clean-image guarantee beyond these dated checks is implied.

Raw JSON scans include every installed package/version. The final image keeps inherited Debian `status.d` records plus added library-package records/checksums/copyright. `/usr/share/proppulse/runtime-components.json` lists copied files and versions; `libc-bin` explicitly records its partial inclusion (required `ldconfig` only). No package metadata is erased to improve scanning. Private inventories, hashes, scans and test results remain under ignored `backend/data/odds_runs/container-image-remediation/`.

## What changed and why

The multistage build retains the complete maintained distroless base and official CPython; it is not a hand-built scratch/glibc filesystem. The base's [keyless signature](https://github.com/GoogleContainerTools/distroless#how-do-i-verify-distroless-images) passed verification against Google issuer `https://accounts.google.com` and identity `keyless@distroless.iam.gserviceaccount.com`.

`docker/assemble_runtime.py` checks the native-library closure and copies only missing, explicitly reviewed Debian library packages, with attribution and version metadata. Required base libraries include libc, OpenSSL, libgcc/libstdc++, OpenMP, zlib and CA/timezone data. Added libraries support bz2, crypt, dbm, ffi, gdbm, lzma, curses/readline, SQLite and UUID. Versions include libc **2.41-12+deb13u4**, OpenSSL **3.5.7-1~deb13u3**, SQLite **3.46.1-7+deb13u2**, and libgomp/libstdc++ **14.2.0-19**.

CPython 3.11's [ctypes lookup](https://github.com/python/cpython/blob/3.11/Lib/ctypes/util.py) needs `/sbin/ldconfig -p`; the verified Debian binary and a cache generated against the assembled runtime are retained. Shells, apt/dpkg, compiler, mount/nsenter, passwd/login, Perl, ACL and systemd libraries are not runtime requirements and are absent. The default command is exec-form `python -m uvicorn`, UID/GID **10001**, with `/app/data` owned by 10001. Read-only root, no-new-privileges and dropped capabilities are exercised, not merely documented.

The official slim baseline already cannot import `_tkinter` because Tcl/Tk is absent; source inspection found no app/supported-tooling GUI imports. Unavailable GUI tooling is excluded, rather than adding an X11/Tk stack. Numba's optional uninstalled TBB backend is unchanged; standalone library analysis accounts for wheel-private RPATHs and records that optional absence. Actual OpenMP JIT/parallel and native ML execution passed without a runtime `LD_LIBRARY_PATH` workaround. pip/setuptools/wheel, bundled ensurepip and Python development headers are excluded; no Python application package was upgraded.

## Findings resolved or retained

This is component removal, not a claim that vulnerable upstream implementations were patched. The selected runtime no longer includes unnecessary `libacl1`, `libsystemd0`, `libudev1`, Perl and administrative packages. For example, removal eliminates the installed ACL component associated with [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369). The earlier homed/Perl findings also required distinguishing daemon/module availability from broad source-package attribution; scanner-row removal is not counted as a newly demonstrated exploit fix.

Remaining high rows, with exact retained versions:

| Installed component | High IDs | Actual scope |
| --- | --- | --- |
| `libuuid1` **2.41.5-0+deb13u1** | [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | Source-package findings concern mount/nsenter/helpers, which are absent. UUID library functionality is preserved. |
| `libncursesw6`, `libtinfo6` **6.5+20250216-2** | [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) (two rows) | Affected `infocmp` CLI is absent; Python curses/readline libraries remain compatible. |

No compatible stable fixed versions are reported for any of the **67** remaining rows. Debian records unstable fixes/no-dsa dispositions for important cases; unstable libraries were not mixed into this stable runtime. Component absence narrows reachability but does **not** mark these installed package versions fixed or suppress their findings. Medium/low findings remain in the unfiltered JSON inventory.

## PostgreSQL helper disposition

The current official image still contains **gosu 1.19**, built with **Go 1.24.6**, amd64 SHA-256 `52c8749d0142edd234e9d6bd5237dff2d81e71f43537e2f4f66f75dd4b243dd0`, matching the upstream asset. No newer maintained release was established; see [release](https://github.com/tianon/gosu/releases/tag/1.19), [security policy](https://github.com/tianon/gosu/security), and [official PostgreSQL Dockerfile](https://github.com/docker-library/postgres/blob/master/15/alpine3.24/Dockerfile).

Its 61 rows comprise 59 standard-library IDs, one [moby/sys/user parser DoS](https://github.com/moby/sys/security/advisories/GHSA-mjcv-p78q-w5fw) fixed in 0.4.1, and one [Windows-only x/sys issue](https://pkg.go.dev/vuln/GO-2026-5024). The critical [TLS resumption finding](https://pkg.go.dev/vuln/GO-2026-4337) has specific crypto/tls preconditions; package/toolchain detection is not call-graph proof that all 59 standard-library issues execute in gosu. No blanket unreachable/safe claim is made for the original binary.

A fail-closed executable tripwire proved the official entrypoint can cold-initialize and run PostgreSQL directly as UID/GID70 without invoking gosu: PID1 PostgreSQL, CapEff0, NoNewPrivs1, read-only root, no network or host ports. That **alone is a mitigation** and leaves the official image's 61 findings installed.

The selected derivative goes further: it removes the unused helper and enforces UID70 in image configuration. The effective filesystem has no gosu; the actual scan has no Go findings. Official entrypoint, server, `pg_dump` and `pg_restore` hashes are unchanged. Unexpected root startup fails closed (missing helper), not through a custom privileged replacement. Parent image layers remain inherited; use the derivative, not the original parent. Operators must provision data/socket mounts for UID70; root-assisted ownership repair and automatic chown of root-owned volumes are intentionally unsupported.

## Verification and reproduction

Passed on the selected images:

- Fresh complete wheel installation, build-time `pip check`, 62-version lock parity and current Python audit zero.
- 76 available standard-library C-extension imports; real ctypes library discovery, CA roots, DNS/NSS, timezone, compression, SQLite and dbm operations.
- NumPy/pandas/SciPy/scikit-learn/XGBoost fit, SHAP explanation, Numba OpenMP parallel JIT, bcrypt and HS256 verification; expired/none/wrong-algorithm JWT rejection.
- Real default Uvicorn startup and `/health`/`/ready` over the private Docker network, UID10001, CapEff0, read-only root, no-new-privileges, no setuid/setgid files and restricted build context.
- Fresh PostgreSQL15.19 bootstrap to Alembic **20261022_05**, separate owner/app roles and five denied DDL/provider-DML checks.
- Cookie-authenticated saved selection/slip persistence, ownership denial and expired-offer refusal. Atomic custom-format restore preserved **15 tables / 37 rows**, exact identities/hashes, original session, password login and logout. No unexpected schema/row changes or provider HTTP attempts.
- **12 focused guard tests**; 28 backend layers/94 app entries inspected with no private paths, run secrets or private environment values. No full backend/frontend suite rerun; no frontend/product/auth implementation changed.

Fixture backup: **37,741 bytes**, SHA-256 `c1c48326e3f36b36cc3dfb2a8c999d8f236b3d7a0713989acb14730b201774e2`; private dump retained. Early attempts corrected readiness seeing initdb's temporary server and Docker Desktop's tmpfs archive-copy limitation; backup/restore now streams binary data. Docker's host-full-disk/read-only incident was recovered without reset/prune/volume deletion; only five new regenerable public-image exports with completed scans were removed. Existing private artifacts were preserved.

Commands assume a clean reviewed source tree containing these changes. This run used `git archive` of the checkpoint with only Dockerfile/ignore/assembly changes overlaid, excluding unrelated working modifications. Package repositories change, so a later rebuild needs its own identities and checks.

```powershell
docker build -t proppulse-backend:hardened backend
Get-Content -Raw backend/docker/postgres.Dockerfile | docker build -t proppulse-postgres:nonroot -
$py = '.\backend\venv\Scripts\python.exe'
& $py backend/tests/container_postgres_regression.py --evidence-dir backend/data/odds_runs/container-image-remediation/pg/reproduce
& $py backend/tests/postgres_gosu_probe.py --evidence-dir backend/data/odds_runs/container-image-remediation/pg/reproduce-gosu
```

The regression owns only newly created `pp-image-*` resources, checks unique run labels, publishes no ports and cleans them up. Existing names/private evidence cause refusal, never adoption or overwrite. It generates private dummy settings for subsequent native checks. Mount `container_runtime_probe.py` beside `production_image_probe.py` at `/verification`, supply its private `api-0.env`, then run `python /verification/container_runtime_probe.py` with `--network none --read-only --cap-drop ALL --security-opt no-new-privileges` and a UID10001 `/tmp` tmpfs. Final image scans used exported immutable images and `trivy image --input ... --scanners vuln --list-all-pkgs --format json`; compare against the same database and record its timestamp. Never introduce real provider keys/test against development PostgreSQL.

## Changed files

- Packaging: `backend/Dockerfile`, `backend/.dockerignore`, `backend/docker/assemble_runtime.py`, `backend/docker/postgres.Dockerfile`.
- New checks: `backend/tests/container_runtime_probe.py`, `container_postgres_regression.py`, `container_postgres_auth.py`, `postgres_gosu_probe.py`, `test_container_regression_guards.py` (all under `backend/tests/`).
- Existing helper integration: `backend/tests/production_stack_control.py` image defaults and `production_gateway_probe.py` numeric UID compatibility.
- Reports: this document and `docs/security-stage3-production-verification.md`.

## Remaining release conditions

Public deployment is **not approved**. Retain review/monitoring of all 67 backend rows and stable distro updates; configure the chosen host's HTTPS gateway, quotas, exact origins/cookies, private DB TLS/roles, secrets, encrypted backups/restore and monitoring. Keep UID70 storage provisioning for the selected DB image. Browser/fleet/load/cross-architecture and managed-host recovery were not re-certified here. Stateless token revocation, deferred Tailwind development advisory, source completeness, historical odds movement and provider availability remain unchanged limitations. No hosting platform is selected or configured.
