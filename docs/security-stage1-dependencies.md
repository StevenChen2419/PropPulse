# Production security Stage 1: dependency remediation

October 23, 2026. Starting HEAD: `b9348b052fc57cf39db5e05387e3b6e4f16f8d7b`.
Implementation used no development database changes, provider requests, deployment, commit or push. A subsequent owner instruction authorizes exactly one local Stage 1 commit.

**Stage 2 follow-up:** [Authentication/API hardening](security-stage2-auth-api.md) replaces python-jose with PyJWT and removes the two residual Python advisories from the new fresh graph. The Stage 1 audit/checkpoint evidence below is historical.

## Changes and exposure

Current PyPI audit reproduces 64 raw entries across 11 packages, representing **34 distinct advisories**, after deduplicating repeated IDs and aliases. Authoritative GitHub advisory metadata confirms all ranges/fixes below; none withdrawn. Audit the installed graph, not just direct requirements.

| Package | Original installed -> selected | Relationship/use and disposition |
| --- | --- | --- |
| FastAPI | 0.111.0 -> 0.135.4 | Direct production framework. Selected release declares Starlette >=0.46.0 without an upper bound, Pydantic >=2.9.0. Allows patched Starlette without an incompatible override. |
| Starlette | 0.37.2 -> 1.3.1 | Transitive, now explicitly pinned; production ASGI/middleware/URL handling. Seven advisories fixed. Optional StaticFiles, HTTPEndpoint and form features absent from app source. Major update required for available URL/parser fixes. |
| python-multipart | 0.0.9 -> 0.0.31 | Direct installed parser. Seven advisories fixed. No production upload/form routes currently exist; isolated tests verify file/parser compatibility. |
| anyio | 4.13.0 -> 4.14.2 | Transitive runtime, explicitly pinned. Two advisories fixed; no process workers or direct IDNA TLS helpers used. |
| cryptography | 48.0.0 -> 50.0.0 | jose extra, explicitly pinned runtime HMAC backend. Four advisories fixed, including bundled OpenSSL. No certificate-verifier/PKCS7 app use. Major update necessary for complete available fixes. |
| pyasn1 | 0.6.3 -> 0.6.4 | Transitive jose/rsa fallback, explicitly pinned. Three decoder/resource advisories fixed; ASN.1 parsing absent from HS256 path. |
| python-dotenv | 1.0.1 -> 1.2.2 | Direct config/ingestion tooling. Symlink-write advisory fixed; source loads files, never set_key/unset_key. |
| scikit-learn | 1.4.2 -> 1.5.2 | Direct supported ML tooling, not imported by serving app. Sensitive-data advisory fixed; affected transformation functionality unused. |
| pip | 25.0.1 -> 26.2.2 | Build/install only. Six advisories fixed. Bootstrap instructions and Docker explicitly update installer. |
| ujson | 5.12.1 -> absent | Old FastAPI hard dependency; no app/tooling imports or UJSONResponse. Modern FastAPI base drops it. One advisory eliminated from fresh graph. |
| python-jose | 3.5.0 retained | Direct production JWT. DER public-key/HMAC confusion remains without a fix. Private symmetric HS256-only secret and explicit decode algorithm remove the described asymmetric-key precondition. Authentication architecture retained. |
| ecdsa | 0.19.2 retained | Required transitive jose fallback. Minerva signing timing remains without a fix. App uses cryptography HMAC, never EC signing; not reachable under current configuration. Package remains vulnerable. |
| Pydantic/core | 2.7.1/2.18.2 -> 2.9.2/2.23.4 | Compatible validation update required by selected FastAPI. Contracts verified by regression tests. |

Production-exposed framework findings receive priority even where optional vulnerable features are unused. Installed-but-unreachable findings are still fixed when compatible. No demonstrated exploit is required to justify remediation. Remaining JWT/EC findings are constrained by the current configuration, not declared safe or fixed.

Other resolved transitives are recorded exactly in `backend/requirements.lock.txt`. Existing bcrypt 4.0.1/passlib 1.7.4, SQLAlchemy 2.0.30, psycopg2-binary 2.9.9 and Alembic 1.13.1 are retained. The pre-existing certifi 2026.10.19 change is preserved. Existing environment SHAP 0.52.0 differed from requirements 0.45.0; fresh installation honors 0.45.0. NumPy is constrained to 1.26.4 for that compiled ABI with pandas 2.2.2. Synthetic in-memory fit/predict/SHAP smoke passed; no model files or training scripts were run.

## Reproducible installation

One pip constraints lock (`requirements.lock.txt`), referenced by `requirements.txt`, pins the reviewed graph. Docker admits/copies the lock. Keep manifest and lock together; intentional upgrades require resolution, audit and tests. Existing development venv is unchanged: use a fresh environment to avoid old orphan dependencies.

From repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.2.2
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

The pip constraint alone does not upgrade an installer; the explicit bootstrap step is required. Local verification uses Python 3.12.10 Windows; Docker baseline is Python 3.11 Linux. This is version locking, not wheel hashes or an OS/system-library lock. Re-audit on the actual deployment target. Audit tooling is separate from application dependencies.

## Verification and remaining risk

Private outputs remain ignored under `backend/data/odds_runs/security-stage1/`. An early audit/import attempt ran before installation finished; its partial result is invalid and is not final evidence.

| Final check | Result |
| --- | --- |
| Fresh Windows Python 3.12.10 environment | Installation successful; all 66 installed packages exactly match active lock constraints, including pip 26.2.2; locked install dry-run has zero pending changes. Existing development venv untouched. |
| Dependency conflict check | `pip check`: no broken requirements. |
| Final installed-environment PyPI audit | 3 raw entries in 2 packages = **2 distinct advisories**, ecdsa and python-jose; expected audit exit 1. **32 of 34 original distinct advisories resolved/eliminated.** No advisory suppressions. |
| Linux Python 3.11 resolution | Cached Linux image, application not started, only two requirements files mounted read-only. `pip install --dry-run --ignore-installed` resolved all versions. Only additional package is uvloop 0.23.0, now conditionally pinned; separate exact-version audit found zero advisories. This used the image's existing pip 24.0; final Docker source explicitly bootstraps 26.2.2. No full Linux install/image/runtime test claim. |
| Focused compatibility tests | 6 passed: memory/disk-spooled uploads, multipart size and URLencoded field-count limits, HS256 cryptography backend/roundtrip, signed malformed subjects, asymmetric/unsigned rejection. Zero external HTTP. |
| Full backend checkpoint | **1,117 run, 1,115 passed, 2 skipped**, zero failures/errors. Includes authentication/passwords, CORS, Saved Props/slip ownership, health/readiness, and 282 discovered PostgreSQL scenarios including fresh/repeated Alembic bootstrap and metadata consistency. Skips require an explicitly supplied actual-statistics artifact. |
| Isolation | PostgreSQL 15 temporary container, random loopback host port, tmpfs, task ownership label, no development mounts. Test DB `proppulse_test_security_stage1`; fixtures own random schemas. Global DB guard recorded zero out-of-scope connections; HTTP guard recorded zero external attempts. Zero leftover test schemas; owned container removed. No development service started or queried. |
| Native ML compatibility | Synthetic in-memory XGBoost fit/predict, sklearn metric, SHAP TreeExplainer passed with NumPy 1.26.4/pandas 2.2.2/SciPy 1.17.1/sklearn 1.5.2/SHAP 0.45.0. No training script or saved artifacts used. |
| Frontend | Clean npm install, 116 tests, TypeScript, production build and 4 Chrome production smoke tests passed. Final production audit zero; full audit 3 moderate package entries = 1 distinct development advisory. |
| Independent review | No actionable code defects. Uvicorn configuration load with upgraded transitives passed without application lifespan. |

No application regression was found. Compatibility adjustment is the NumPy ABI constraint and required Pydantic update. Starlette emits a TestClient deprecation for httpx (still supported); moving tests/application HTTP clients to httpx2 is outside this stage and unnecessary for passing compatibility.

**Sufficient to advance to Stage 2**, with the two unpatched Python advisories and one deferred build-tool advisory explicitly retained for follow-up. This is not zero-vulnerability certification or public-release approval. Revisit JWT findings if algorithms/key sources change; keep HS256-only symmetric secrets. Do not compile untrusted CSS with the affected build toolchain.

Not run: full new Linux runtime/image build, Linux native execution or system OpenSSL/OS-image audit, actual retained-data/provider walkthrough, full browser/E2E integration suite, public HTTPS/proxy/load checks, or development migrations. Those are target deployment/integration checks, not evidence of success here. No frontend dependency changed; focused production browser checks were sufficient. No configured lint gate exists.

## Git preservation

Starting binary diff, exact six-file backups, status and SHA-256 manifest are private under `baseline/`. At the implementation checkpoint, HEAD remained the requested checkpoint and the index was empty. The original `certifi==2026.10.19` addition is retained in the shared requirements file. `fetch_odds.py`, `test_milestone2_ingestion.py`, both pre-existing untracked documents and `.node-version` remain byte-for-byte unchanged.

Stage 1 edits: `backend/requirements.txt`, new `backend/requirements.lock.txt`, `backend/Dockerfile`, `backend/.dockerignore`, new `backend/tests/test_dependency_compatibility.py`, this summary, new npm summary, and the Stage 1 pointer in the existing Phase 9 readiness document. Frontend manifests/lockfile unchanged. The subsequent commit checkpoint includes only these eight reviewed Stage 1 files/hunks. The pre-existing certifi addition in requirements.txt stays unstaged; its version also appears in the new lock as a resolved transitive dependency. The other five unrelated files stay uncommitted. No push or deployment is authorized.

See [npm verification](security-stage1-npm.md): production zero; full audit three moderate package entries represent one build-only selector-parser advisory. No compatible Tailwind 3 patch/minor fix; trusted-source builds only, major migration deferred.

## Verified advisory ranges

Sources: current PyPI advisory API via pip-audit and GitHub Advisory Database API, retrieved October 23. Human links below. Duplicate aliases counted once. Fix cells show upstream first fix, not necessarily the selected patch.

| Package | Advisory | Affected range | First fix |
| --- | --- | --- | --- |
| starlette | [GHSA-2c2j-9gv5-cj73](https://github.com/advisories/GHSA-2c2j-9gv5-cj73) | `< 0.47.2` | 0.47.2 |
| ujson | [GHSA-3j69-69wj-xqx2](https://github.com/advisories/GHSA-3j69-69wj-xqx2) | `<= 5.12.1` | 5.13.0 |
| python-jose | [GHSA-3qf3-8w2g-rqmx](https://github.com/advisories/GHSA-3qf3-8w2g-rqmx) | `<= 3.5.0` | **None published** |
| pip | [GHSA-4xh5-x5gv-qwph](https://github.com/advisories/GHSA-4xh5-x5gv-qwph) | `<= 25.2` | 25.3 |
| cryptography | [GHSA-537c-gmf6-5ccf](https://github.com/advisories/GHSA-537c-gmf6-5ccf) | `>= 0.5.0, < 48.0.1` | 48.0.1 |
| pip | [GHSA-58qw-9mgm-455v](https://github.com/advisories/GHSA-58qw-9mgm-455v) | `<= 26.0.1` | 26.1 |
| python-multipart | [GHSA-59g5-xgcq-4qw3](https://github.com/advisories/GHSA-59g5-xgcq-4qw3) | `< 0.0.18` | 0.0.18 |
| anyio | [GHSA-5p39-cfhj-2xmp](https://github.com/advisories/GHSA-5p39-cfhj-2xmp) | `< 4.14.2` | 4.14.2 |
| python-multipart | [GHSA-5rvq-cxj2-64vf](https://github.com/advisories/GHSA-5rvq-cxj2-64vf) | `< 0.0.30` | 0.0.30 |
| python-multipart | [GHSA-6jv3-5f52-599m](https://github.com/advisories/GHSA-6jv3-5f52-599m) | `< 0.0.30` | 0.0.30 |
| pip | [GHSA-6vgw-5pg2-w6jp](https://github.com/advisories/GHSA-6vgw-5pg2-w6jp) | `< 26.0` | 26.0 |
| anyio | [GHSA-82r6-8w77-94w6](https://github.com/advisories/GHSA-82r6-8w77-94w6) | `< 4.14.2` | 4.14.2 |
| starlette | [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) | `>= 0.4.1, < 1.3.1` | 1.3.1 |
| starlette | [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) | `<= 1.0.0` | 1.0.1 |
| pyasn1 | [GHSA-8ppf-4f7h-5ppj](https://github.com/advisories/GHSA-8ppf-4f7h-5ppj) | `<= 0.6.3` | 0.6.4 |
| starlette | [GHSA-f96h-pmfr-66vw](https://github.com/advisories/GHSA-f96h-pmfr-66vw) | `< 0.40.0` | 0.40.0 |
| cryptography | [GHSA-g6cj-pr64-35w5](https://github.com/advisories/GHSA-g6cj-pr64-35w5) | `>= 44.0.0, < 50.0.0` | 50.0.0 |
| pyasn1 | [GHSA-hm4w-wwcw-mr6r](https://github.com/advisories/GHSA-hm4w-wwcw-mr6r) | `<= 0.6.3` | 0.6.4 |
| pip | [GHSA-jp4c-xjxw-mgf9](https://github.com/advisories/GHSA-jp4c-xjxw-mgf9) | `< 26.1` | 26.1 |
| Starlette | [GHSA-jp82-jpqv-5vv3](https://github.com/advisories/GHSA-jp82-jpqv-5vv3) | `< 1.3.0` | 1.3.0 |
| scikit-learn | [GHSA-jw8x-6495-233v](https://github.com/advisories/GHSA-jw8x-6495-233v) | `< 1.5.0` | 1.5.0 |
| cryptography | [GHSA-jwv3-5hgf-82ww](https://github.com/advisories/GHSA-jwv3-5hgf-82ww) | `>= 42.0.0, < 49.0.0` | 49.0.0 |
| cryptography | [GHSA-m2h6-j472-rp4c](https://github.com/advisories/GHSA-m2h6-j472-rp4c) | `>= 45.0.0, < 49.0.0` | 49.0.0 |
| pyasn1 | [GHSA-m4p7-r5rc-7g4j](https://github.com/advisories/GHSA-m4p7-r5rc-7g4j) | `< 0.6.4` | 0.6.4 |
| python-dotenv | [GHSA-mf9w-mj56-hr94](https://github.com/advisories/GHSA-mf9w-mj56-hr94) | `< 1.2.2` | 1.2.2 |
| python-multipart | [GHSA-mj87-hwqh-73pj](https://github.com/advisories/GHSA-mj87-hwqh-73pj) | `< 0.0.26` | 0.0.26 |
| python-multipart | [GHSA-pp6c-gr5w-3c5g](https://github.com/advisories/GHSA-pp6c-gr5w-3c5g) | `< 0.0.27` | 0.0.27 |
| pip | [GHSA-qwm4-qh6w-59xr](https://github.com/advisories/GHSA-qwm4-qh6w-59xr) | `< 26.2.0` | 26.2.0 |
| python-multipart | [GHSA-v9pg-7xvm-68hf](https://github.com/advisories/GHSA-v9pg-7xvm-68hf) | `< 0.0.31` | 0.0.31 |
| pip | [GHSA-wf93-45jw-7689](https://github.com/advisories/GHSA-wf93-45jw-7689) | `< 26.1.2` | 26.1.2 |
| ecdsa | [GHSA-wj6h-64fc-37mp](https://github.com/advisories/GHSA-wj6h-64fc-37mp) | `>= 0` | **None published** |
| python-multipart | [GHSA-wp53-j4wj-2cfg](https://github.com/advisories/GHSA-wp53-j4wj-2cfg) | `< 0.0.22` | 0.0.22 |
| starlette | [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) | `< 1.1.0` | 1.1.0 |
| starlette | [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c) | `< 1.1.0` | 1.1.0 |
