# Milestone 3H: frontend build and dependency evidence

Verified October 16, 2026. This supports the [staging and recovery report](milestone-3h-staging-recovery.md).
Reviewed the complete Phase 3F integration/security and Phase 3G hardening reports,
current package/lockfile, Next/Tailwind/PostCSS configuration, layout and browser
runner configuration. No frontend source, dependency or lockfile change was made.

## Actual verification

Existing Windows installation: Node **24.15.0**, npm **11.12.1**, Next **15.5.28**,
React/React DOM **19.0.9**, PostCSS **8.5.30**, sharp **0.35.5**. Next's declared
engine range includes Node 24; sharp requires >=20.9.0. Use a maintained Node
release satisfying both and verify native packages on the target platform.

| Check | Actual result |
| --- | --- |
| `npm test` | 59 passed, zero failed/skipped/cancelled; 1.667 seconds; exit 0 |
| `npx tsc --noEmit` | Exit 0 |
| `npm run build` | Exit 0; ten static pages; compilation 1.746 seconds |
| `npm ls --all` | Exit 0; optional missing peers/platform packages are not required dependency failures |
| `npm audit --json` | Exit 1; seven development entries: five high, two moderate, zero critical |
| `npm audit --omit=dev --json` | Exit 0; zero findings |

Build used explicit `NEXT_PUBLIC_API_URL=http://localhost:8000` and
`NEXT_TELEMETRY_DISABLED=1`. The public API URL is embedded in client assets;
rebuild for a different API origin. There is no secret requirement for building
these pages. No database, application server or provider was started by this work.
The build passed using the existing installation and caches; a clean install,
offline font build, Linux/native-image build and reproducible byte-identical
artifact were **not** demonstrated. Total build wall time was not separately
instrumented; the compilation time above is Next's logged substage.

Initial sandbox registry audits failed to reach npm and could not produce an
advisory result. Registry-only permitted reruns produced the final results above.
Raw final audit JSON, stderr and test/build/dependency logs are ignored under
`backend/data/odds_runs/m3h/`. Audit cache is confined to that evidence directory.
Audit requests went to npm's registry, not sports providers. Audit results describe
the registry's known advisories at execution time and do not prove absence of bugs.

Reviewed lockfile SHA-256:
`0e0247297bc4d2d5c7688cdcb401111015927262c13ec4d4efd79d18f38efd1f`.
No install, force-fix, Tailwind 4 migration or incompatible override was run.
Browser matrix execution is recorded by the main rehearsal owner in the main
report; frontend unit/static-build results alone do not establish browser behavior.
There is no standalone ESLint gate in the current package scripts.

Final checkpoint reran units (**59 passed**, 1.520s), TypeScript and production
build (both exit 0; ten pages), and registry audits (complete exit 1: seven
development entries, five high/two moderate; production exit 0: zero).
The lockfile digest above is unchanged. Fresh logs are ignored under
`backend/data/odds_runs/m3h-checkpoint/`; failed initial sandbox network attempts
are retained separately from the successful registry-only audit responses.
No clean install or isolated builder claim is added by this rerun.

## Remaining seven findings

These are seven dependency entries propagating **two root advisories**, rather
than seven independent vulnerabilities. All seven have `dev: true` in the lockfile.

| Installed entry | Severity | Dependency/exposure |
| --- | --- | --- |
| braces 3.0.3 | high | Recursive glob pattern parsing; root advisory |
| micromatch 4.0.8 | high | Propagates braces |
| fast-glob 3.3.3 (under Tailwind) | high | Propagates micromatch/braces |
| chokidar 3.6.0 | high | Watch tooling propagates braces |
| tailwindcss 3.4.19 | high | Direct CSS build dependency propagates these chains |
| postcss-selector-parser 6.1.4 | moderate | CPU exhaustion parsing selectors; root advisory |
| postcss-nested 6.2.0 | moderate | Propagates selector-parser |

The fresh [braces advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
still lists <=3.0.3 as affected with no patched version. Deeply nested patterns
can exhaust the Node call stack. The
[selector-parser maintainer advisory](https://github.com/postcss/postcss-selector-parser/security/advisories/GHSA-rj75-hqrm-r3gf)
identifies a fix in 7.1.6, outside the current parser major. Untrusted selectors
can consume CPU; the maintainer distinguishes trusted ordinary builds from
synchronous parsing of attacker-controlled selectors. Current Tailwind content
patterns are repository literals; Next's PostCSS config executes Tailwind and
autoprefixer. Browser clients do not submit CSS/globs to this pipeline. An
untrusted pull request can still change build configuration and execute code.

The audit suggests a Tailwind 4.3.3 major change for several paths. No supported
compatible remediation was established in this milestone. Isolation reduces
blast radius and availability exposure; **it does not remediate either advisory**.
Production release still requires an accountable acceptance of the bounded build
risk or a separately verified supported toolchain migration.

## Required release build strategy

Use one ephemeral VM or unprivileged container per build, created from a reviewed
base image pinned by digest. A container is optional; a short-lived VM suffices.
Do not introduce Redis, a build database or other application infrastructure.

1. Export the exact reviewed source revision into a fresh workspace, excluding
   `.env*`, dependency/build caches, backend evidence and private data. Record
   source and lockfile digests. Review lockfile registry/resolution changes as code.
   Install the trusted lockfile with `npm ci --ignore-scripts --no-audit --fund=false`
   in this copy; never run `npm ci` against the developer's active installation.
   [npm documents](https://docs.npmjs.com/cli/v11/commands/npm-ci/) that `ci` refuses
   a manifest/lock mismatch and removes an existing installation, and that
   `ignore-scripts` suppresses package lifecycle scripts. It still permits the
   explicitly invoked build script, which executes repository configuration.
2. Use a non-root, non-administrator identity with no host home/credential mounts,
   no production secrets, no cloud identity, no provider keys, no database endpoint
   credentials, and no Docker socket or daemon privileges. Deny access to host,
   private networks and metadata endpoints at the runner boundary, including
   loopback/host-gateway routes where applicable. Environment-variable absence
   alone is insufficient isolation.
3. Separate dependency download from compilation. Permit only registry and vetted
   font egress through a controlled proxy; enforce destination limits outside
   repository code. `next/font/google` imports Inter and may download from Google
   during build. A fully network-disabled clean build requires a reviewed vendored
   font or controlled prefetch/cache design. The successful local cached build
   does not prove this requirement. Disable general compilation egress once inputs
   are available; never permit sports-provider hosts.
4. Apply initial enforced limits of two CPUs, 4 GiB RAM, 512 processes, bounded
   scratch disk and a ten-minute job timeout; tune with clean-build evidence on the
   selected runner. The filesystem should expose reviewed source read-only where
   practical, with a separate writable job copy/scratch for `.next`, npm and
   TypeScript output. Record terminations as failed builds. These starting limits
   are policy proposals, not measured capacity claims.
5. Run units, type checks, production build and audits against the reviewed input.
   Supply only the public API URL and telemetry setting. A malicious config must
   have no publish or signing token to steal. Audit network access belongs in a
   distinct permitted registry step, not unrestricted build egress.
6. Assemble a fresh runtime directory with `package.json`, lockfile, reviewed Next
   config, `.next` and `public` if present, and install runtime dependencies using
   `npm ci --omit=dev --ignore-scripts --no-audit --fund=false`. Do not compile after
   omitting Tailwind. `next.config.ts` currently has no standalone output setting;
   do not assume `.next/standalone` exists. Run `npm start` without development
   reload flags and verify target-platform optional binaries.
7. Separate untrusted PR validation from release publishing. PR jobs receive no
   publish/signing credentials and cannot write shared release caches. A protected
   release job consumes only the reviewed revision's verified artifact; it does
   not execute fork-supplied scripts with privileged tokens. Verify artifact hashes
   after transfer. Record SHA-256 of the final immutable archive/image, source
   revision, lockfile and public build settings; deploy images by digest. Sign the
   digest or attach trusted provenance using a separate narrowly authorized job
   where the eventual registry supports it. A hash alone is integrity evidence,
   not a signature or provenance guarantee. No artifact was published or signed.

## Local reproducibility versus hosting requirements

| Safeguard | Local status in this milestone |
| --- | --- |
| Reviewed manifests/configuration, fixed lockfile, audited graph | Inspected; audits and existing-install build executed |
| Public-only API build setting, telemetry disabled | Executed |
| Synthetic/disposable database application rehearsal | Owned separately; see main report |
| Fresh `npm ci --ignore-scripts` release copy | Procedure specified; not executed |
| Ephemeral unprivileged builder, read-only mounts | Reproducible with local VM/container; not verified by the host build |
| CPU/RAM/PID/disk/wall-time enforcement | Reproducible locally; not enforced or stress-tested for this host build |
| Denied DB/Docker socket/private network and controlled font/registry egress | Required runner configuration; not proven by this host build |
| Linux/native dependency and minimal runtime packaging | Requires target-platform rehearsal; not verified |
| PR privilege/cache segregation, protected publisher, signing/provenance | Requires selected CI/registry configuration; not implemented or verified |

The current host build is functional evidence, not an isolated release builder
certification. Do not approve unrestricted or secret-bearing builds based on the
zero production-only audit. Retain the seven findings in the release risk register,
re-audit before release, and schedule toolchain migration separately with visual
and browser regression coverage.
