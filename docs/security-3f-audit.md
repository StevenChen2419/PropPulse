# Milestone 3F frontend dependency security evidence

Phase 3G follow-up: [security hardening and current deployment requirements](milestone-3g-security-hardening.md).
The historical nine-entry result below is superseded by seven entries after
removing unused ESLint tooling; production-only findings remain zero. The
PostCSS override and Tailwind 3 are retained. See Phase 3G for startup/readiness,
authentication hardening and remaining build-isolation requirements.

Audit date: October 15, 2026. Node **24.15.0**, npm **11.12.1**. The fresh
baseline `npm audit --json` reproduced **17 dependency entries: 1 critical,
14 high, 2 moderate**. Entries include propagated dependency findings; these
are not seventeen distinct CVEs. The final complete audit reports **9 entries:
0 critical, 7 high, 2 moderate**. `npm audit --omit=dev --json` reports **zero**.
Audit JSON and the final frontend unit log are ignored under
`backend/data/odds_runs/m3f-security/`. The original package manifests are retained
there for reproducing the baseline without changing the application installation.

The final review checkpoint reran both registry audits against the unchanged
lockfile: complete audit **9 entries, 0 critical / 7 high / 2 moderate**, exit 1;
production-only audit **zero**, exit 0. Evidence is retained in ignored
`backend/data/odds_runs/m3f-checkpoint/`. The same checkpoint passed **59 frontend
unit tests**, with zero failures, cancellations or skips (1.578 seconds),
`npx tsc --noEmit`, and the Next 15.5.28 production build using
`NEXT_PUBLIC_API_URL=http://localhost:8000` (ten static pages). No build warning
or functional failure occurred. The npm notice advertising npm 12.2.0 is
informational; npm was not upgraded. The complete package/lockfile diff and
`npm ls next react react-dom postcss sharp --depth=1` were reviewed; the expected
security/framework versions and their supporting dependency graph resolve
without invalid or missing dependencies. No further package changes were made.

## Changes and compatibility

- Next.js **15.3.2 → 15.5.28**, a maintained same-major security release;
  matching development `eslint-config-next` **15.3.2 → 15.5.28**.
- React and React DOM **19.0.0 → 19.0.9**, matching patch versions.
- Next regenerated `frontend/next-env.d.ts` with the route-types reference
  `./.next/types/routes.d.ts`; this is retained as the upgraded framework's
  generated TypeScript integration, verified by the build and type check.
- Direct development PostCSS **8.5.15 → 8.5.30**, declared `^8.5.30`.
  Next still pins PostCSS 8.4.31. A narrowly scoped `next.postcss` npm override
  references the direct patched PostCSS declaration. `npm ls postcss` confirms
  Next and the CSS toolchain resolve 8.5.30. This compatible-major override
  needs maintenance until upstream updates its pinned dependency.
- Targeted compatible lockfile updates install sharp **0.35.5** (previously
  0.34.5, within Next's declared optional range), nanoid **3.3.20** (3.3.12),
  source-map-js **1.2.2** (1.2.1), baseline-browser-mapping **2.11.29** (2.10.32),
  browserslist **4.29.3** (4.28.2), js-yaml **4.3.2** (4.1.1),
  brace-expansion **1.1.21 / 5.0.12** (1.1.15 / 5.0.6), and
  postcss-selector-parser **6.1.4** (6.1.2; remaining moderate below).

No `npm audit fix --force`, framework major upgrade, Tailwind migration,
application schema/configuration change, or provider request was performed.
Install lifecycle scripts were disabled. Existing platform native binaries and
optional packages were sufficient for the verified Windows production build.
Next declares Node `^18.18.0 || ^19.8.0 || >=20.0.0` and React `^19.0.0`;
sharp 0.35.5 requires Node `>=20.9.0`. The tested Node 24 satisfies both. Production
should use a maintained Node release satisfying **>=20.9.0**, with the lockfile.
Deployment image/platform verification remains necessary.

The [official October 14 Next.js security release](https://nextjs.org/blog/nextjs-security-update-october-14-2026)
identifies 15.5.28 as Maintenance LTS and addresses upstream cache/typed-array
RCE (GHSA-673q-mjm6-r5xr / React GHSA-xqc2-xf4c-x3h3), SVG image optimization
RCE (GHSA-2464-fhr4-w9xw / CVE-2026-96889), and Server Actions DoS
(GHSA-p3m5-59mp-jv5r / React GHSA-h3gv-c5rc-p453).
Its sharp requirement is >=0.35.5. These current official advisories are
considered in addition to the registry baseline, which did not enumerate every
new advisory. Do not infer an old release is safe from audit output alone.

The [React team's RSC security guidance](https://react.dev/blog/2025/12/11/denial-of-service-and-source-code-exposure-in-react-server-components)
requires framework/RSC patches even when application code has no Server Actions.
Updating only the public React package would not fix Next's compiled RSC code;
the maintained Next release is the essential framework remediation.
The [PostCSS maintainer advisory](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp)
documents why the previous parser fixes were insufficient; the override uses
a later patched 8.x release.

## Verification

| Executed check | Result |
| --- | --- |
| `npm test` | 59 passed; 0 failed/skipped/cancelled |
| `npx tsc --noEmit` | Exit 0 |
| `npm run build`, API `http://localhost:8000` | Exit 0; Next 15.5.28, all 10 static pages generated |
| `npm ls postcss` | Exit 0; one deduplicated patched 8.5.30 |
| Final `npm audit --json` | Exit 1 because 9 findings remain |
| Final `npm audit --omit=dev --json` | Exit 0; zero findings |

The first sandboxed build failed because existing `next/font` could not fetch
Inter from Google Fonts (EACCES). A permitted rerun completed. This is a build
network dependency to document for restricted CI. Browser coverage is recorded
in the main Milestone 3F report by the integration owner. Standalone lint was
not claimed; the existing unconfigured lint workflow remains separate.

## Remaining vulnerabilities and release decisions

The seven high entries share **one unresolved root advisory**:
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm),
CVE-2026-93687, deeply nested glob braces can exhaust the stack. The affected
package is braces **3.0.3** (all <=3.0.3); no patched version is published.
Propagated high entries are micromatch **4.0.8**, fast-glob **3.3.1 / 3.3.3**,
chokidar **3.6.0**, @next/eslint-plugin-next **15.5.28**,
eslint-config-next **15.5.28**, and tailwindcss **3.4.19**. All are development
dependencies. The application does not accept user-supplied glob patterns;
trusted repository source/configuration is the build input. They are not in
the production dependency audit, but untrusted build/CI input is a relevant
attack surface. This remains a **release blocker for unrestricted builds or
CI accepting untrusted patterns**, requiring remediation or an explicit,
evidence-backed production artifact/CI isolation decision before release.

The two moderate entries share
[GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf):
postcss-selector-parser **6.1.4** (<7.1.6), and propagated postcss-nested
**6.2.0**. These are development CSS tooling. A >=7.1.6 parser is outside
postcss-nested's declared parser major. No unsupported major override was
forced. Trusted CSS build input limits current exposure; untrusted CSS builds
must remain isolated. This is a tracked development risk, not an identified
runtime application vulnerability.

Separately scoped remediation: evaluate a supported Tailwind 4 migration
(audit recommends 4.3.3), including PostCSS integration, CSS/configuration,
responsive visual parity, production build and browser regressions. Audit the
result because ESLint's independent glob chain also requires a supported
replacement/upstream fix. Do not downgrade eslint-config-next to the audit's
suggested 14.x merely to remove the reported path. Re-audit after upstream
patches and remove the PostCSS override once Next itself resolves safely.

The frontend's known critical production findings have been remediated, but
this report does **not** declare production readiness. Runtime audit output
does not establish absence of vulnerabilities or secure operational configuration.

## Baseline advisory inventory

The following catalog records exact advisory IDs and affected ranges from the
fresh registry response. Direct baseline findings: production Next 15.3.2;
development PostCSS 8.5.15, eslint-config-next 15.3.2 and Tailwind 3.4.19.
Other listed packages are transitive. PostCSS also had a production transitive
8.4.31 copy under Next. Nanoid, source-map-js and sharp were production
transitives; all remaining package families were development-only. Patched
requirements are the complement of each vulnerable range; braces has no patch.

| Dependency entry | Baseline installed | Use | Final / required remediation |
| --- | --- | --- | --- |
| next | 15.3.2 | Direct production | 15.5.28 maintained security release |
| sharp | 0.34.5 | Transitive production, Next optional image processing | 0.35.5; >=0.35.5 required |
| postcss | 8.4.31 / 8.5.15 | Transitive production / direct development | 8.5.30; >8.5.22 required |
| nanoid | 3.3.12 | Transitive production parser dependency | 3.3.20; >=3.3.18 required |
| source-map-js | 1.2.1 | Transitive production parser dependency | 1.2.2; >=1.2.2 required |
| eslint-config-next | 15.3.2 | Direct development | 15.5.28; braces chain unresolved |
| @next/eslint-plugin-next | 15.3.2 | Transitive development | 15.5.28; braces chain unresolved |
| tailwindcss | 3.4.19 | Direct development | 3.4.19; supported major migration needed |
| braces | 3.0.3 | Transitive development | No published patch |
| chokidar | 3.6.0 | Transitive development | 3.6.0; braces chain unresolved |
| fast-glob | 3.3.1 / 3.3.3 | Transitive development | Unchanged; braces chain unresolved |
| micromatch | 4.0.8 | Transitive development | Unchanged; braces chain unresolved |
| brace-expansion | 1.1.15 / 5.0.6 | Transitive development | 1.1.21 / 5.0.12 required and installed |
| baseline-browser-mapping | 2.10.32 | Transitive development | 2.11.29; >=2.11.0 required |
| browserslist | 4.28.2 | Transitive development | 4.29.3; >4.28.6 required |
| js-yaml | 4.1.1 | Transitive development | 4.3.2; >=4.3.2 required |
| postcss-selector-parser | 6.1.2 | Transitive development | 6.1.4; >=7.1.6 remains required |

Upgrading the parser's major through an override or replacing Tailwind with v4
can change CSS processing semantics; these are migration risks requiring a
separate compatibility and visual review. The tested Next same-major upgrade
adds `next lint` deprecation warnings but does not require an application routing
migration. Lockfile changes are limited to the named packages and their
supporting dependency graph; application runtime source was not edited.

| Package | Advisory | Severity | Affected range |
| --- | --- | --- | --- |
| baseline-browser-mapping | [GHSA-w5vr-8v7q-w6rv](https://github.com/advisories/GHSA-w5vr-8v7q-w6rv) | moderate | >=2.0.0 <2.11.0 |
| brace-expansion | [GHSA-3jxr-9vmj-r5cp](https://github.com/advisories/GHSA-3jxr-9vmj-r5cp) | high | <1.1.16 |
| brace-expansion | [GHSA-3jxr-9vmj-r5cp](https://github.com/advisories/GHSA-3jxr-9vmj-r5cp) | high | >=3.0.0 <5.0.7 |
| brace-expansion | [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) | high | <1.1.17 |
| brace-expansion | [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) | high | >=4.0.0 <5.0.8 |
| brace-expansion | [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | high | >=4.0.0 <5.0.9 |
| brace-expansion | [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | high | <1.1.18 |
| brace-expansion | [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | moderate | <1.1.21 |
| brace-expansion | [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | moderate | >=4.0.0 <5.0.12 |
| brace-expansion | [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7) | high | <1.1.20 |
| brace-expansion | [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7) | high | >=4.0.0 <5.0.11 |
| brace-expansion | [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) | high | <1.1.19 |
| brace-expansion | [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) | high | >=4.0.0 <5.0.10 |
| braces | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | high | <=3.0.3 |
| browserslist | [GHSA-c83g-rgw3-j3cx](https://github.com/advisories/GHSA-c83g-rgw3-j3cx) | high | <=4.28.6 |
| browserslist | [GHSA-73wf-gq98-2v4g](https://github.com/advisories/GHSA-73wf-gq98-2v4g) | high | <=4.28.6 |
| js-yaml | [GHSA-h67p-54hq-rp68](https://github.com/advisories/GHSA-h67p-54hq-rp68) | moderate | >=4.0.0 <=4.1.1 |
| js-yaml | [GHSA-52cp-r559-cp3m](https://github.com/advisories/GHSA-52cp-r559-cp3m) | high | >=4.0.0 <4.3.0 |
| js-yaml | [GHSA-5p4m-2wfm-xmqj](https://github.com/advisories/GHSA-5p4m-2wfm-xmqj) | high | >=4.0.0 <4.3.1 |
| js-yaml | [GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh) | high | >=4.0.0 <4.3.2 |
| nanoid | [GHSA-28wg-ghj8-5hjv](https://github.com/advisories/GHSA-28wg-ghj8-5hjv) | high | <3.3.16 |
| nanoid | [GHSA-2v37-7h3g-55p8](https://github.com/advisories/GHSA-2v37-7h3g-55p8) | high | <3.3.18 |
| next | [GHSA-r2fc-ccr8-96c4](https://github.com/advisories/GHSA-r2fc-ccr8-96c4) | low | >=15.3.0 <15.3.3 |
| next | [GHSA-g5qg-72qw-gw5v](https://github.com/advisories/GHSA-g5qg-72qw-gw5v) | moderate | >=15.0.0 <=15.4.4 |
| next | [GHSA-xv57-4mr9-wg8v](https://github.com/advisories/GHSA-xv57-4mr9-wg8v) | moderate | >=15.0.0 <=15.4.4 |
| next | [GHSA-4342-x723-ch2f](https://github.com/advisories/GHSA-4342-x723-ch2f) | moderate | >=15.0.0-canary.0 <15.4.7 |
| next | [GHSA-9qr9-h5gf-34mp](https://github.com/advisories/GHSA-9qr9-h5gf-34mp) | critical | >=15.3.0-canary.0 <15.3.6 |
| next | [GHSA-w37m-7fhw-fmv9](https://github.com/advisories/GHSA-w37m-7fhw-fmv9) | moderate | >=15.3.0-canary.0 <15.3.7 |
| next | [GHSA-mwv6-3258-q52c](https://github.com/advisories/GHSA-mwv6-3258-q52c) | high | >=15.3.0-canary.0 <15.3.7 |
| next | [GHSA-9g9p-9gw9-jx7f](https://github.com/advisories/GHSA-9g9p-9gw9-jx7f) | moderate | >=10.0.0 <15.5.10 |
| next | [GHSA-h25m-26qc-wcjf](https://github.com/advisories/GHSA-h25m-26qc-wcjf) | high | >=15.3.0-canary.0 <15.3.9 |
| next | [GHSA-ggv3-7p47-pfv8](https://github.com/advisories/GHSA-ggv3-7p47-pfv8) | moderate | >=9.5.0 <15.5.13 |
| next | [GHSA-3x4c-7xq6-9pq8](https://github.com/advisories/GHSA-3x4c-7xq6-9pq8) | moderate | >=10.0.0 <15.5.14 |
| next | [GHSA-q4gf-8mx6-v5v3](https://github.com/advisories/GHSA-q4gf-8mx6-v5v3) | high | >=13.0.0 <15.5.15 |
| next | [GHSA-8h8q-6873-q5fj](https://github.com/advisories/GHSA-8h8q-6873-q5fj) | high | >=13.0.0 <15.5.16 |
| next | [GHSA-26hh-7cqf-hhc6](https://github.com/advisories/GHSA-26hh-7cqf-hhc6) | high | >=15.2.0 <15.5.18 |
| next | [GHSA-3g8h-86w9-wvmq](https://github.com/advisories/GHSA-3g8h-86w9-wvmq) | low | >=12.2.0 <15.5.16 |
| next | [GHSA-ffhc-5mcf-pf4q](https://github.com/advisories/GHSA-ffhc-5mcf-pf4q) | moderate | >=13.4.0 <15.5.16 |
| next | [GHSA-vfv6-92ff-j949](https://github.com/advisories/GHSA-vfv6-92ff-j949) | low | >=13.4.6 <15.5.16 |
| next | [GHSA-gx5p-jg67-6x7h](https://github.com/advisories/GHSA-gx5p-jg67-6x7h) | moderate | >=13.0.0 <15.5.16 |
| next | [GHSA-mg66-mrh9-m8jx](https://github.com/advisories/GHSA-mg66-mrh9-m8jx) | high | >=15.0.0 <15.5.16 |
| next | [GHSA-h64f-5h5j-jqjh](https://github.com/advisories/GHSA-h64f-5h5j-jqjh) | moderate | >=10.0.0 <15.5.16 |
| next | [GHSA-c4j6-fc7j-m34r](https://github.com/advisories/GHSA-c4j6-fc7j-m34r) | high | >=13.4.13 <15.5.16 |
| next | [GHSA-wfc6-r584-vfw7](https://github.com/advisories/GHSA-wfc6-r584-vfw7) | moderate | >=14.2.0 <15.5.16 |
| next | [GHSA-267c-6grr-h53f](https://github.com/advisories/GHSA-267c-6grr-h53f) | high | >=15.2.0 <15.5.16 |
| next | [GHSA-36qx-fr4f-26g5](https://github.com/advisories/GHSA-36qx-fr4f-26g5) | high | >=12.2.0 <15.5.16 |
| next | [GHSA-m99w-x7hq-7vfj](https://github.com/advisories/GHSA-m99w-x7hq-7vfj) | high | >=13.0.0 <15.5.21 |
| next | [GHSA-89xv-2m56-2m9x](https://github.com/advisories/GHSA-89xv-2m56-2m9x) | high | >=14.1.1 <15.5.21 |
| next | [GHSA-68g3-v927-f742](https://github.com/advisories/GHSA-68g3-v927-f742) | moderate | >=13.0.0 <15.5.21 |
| next | [GHSA-4633-3j49-mh5q](https://github.com/advisories/GHSA-4633-3j49-mh5q) | moderate | >=13.0.0 <15.5.21 |
| next | [GHSA-4c39-4ccg-62r3](https://github.com/advisories/GHSA-4c39-4ccg-62r3) | moderate | >=13.0.0 <15.5.21 |
| next | [GHSA-p9j2-gv94-2wf4](https://github.com/advisories/GHSA-p9j2-gv94-2wf4) | high | >=12.0.0 <15.5.21 |
| next | [GHSA-955p-x3mx-jcvp](https://github.com/advisories/GHSA-955p-x3mx-jcvp) | moderate | >=13.0.0 <15.5.21 |
| next | [GHSA-p293-qw3h-jr36](https://github.com/advisories/GHSA-p293-qw3h-jr36) | critical | >=13.4.0 <15.5.24 |
| next | [GHSA-2xp9-vwfh-vxw4](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4) | critical | >=10.0.0 <15.5.24 |
| next | [GHSA-4jqv-mc3x-m676](https://github.com/advisories/GHSA-4jqv-mc3x-m676) | moderate | >=15.0.0 <15.5.27 |
| next | [GHSA-mcj8-r9mp-w47p](https://github.com/advisories/GHSA-mcj8-r9mp-w47p) | moderate | >=15.0.0 <15.5.27 |
| postcss | [GHSA-qx2v-qp2m-jg93](https://github.com/advisories/GHSA-qx2v-qp2m-jg93) | moderate | <8.5.10 |
| postcss | [GHSA-6g55-p6wh-862q](https://github.com/advisories/GHSA-6g55-p6wh-862q) | high | <=8.5.11 |
| postcss | [GHSA-fxqj-rqcc-2cmp](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp) | moderate | <=8.5.22 |
| postcss | [GHSA-r28c-9q8g-f849](https://github.com/advisories/GHSA-r28c-9q8g-f849) | high | <=8.5.17 |
| postcss-selector-parser | [GHSA-w9m9-85wc-3x92](https://github.com/advisories/GHSA-w9m9-85wc-3x92) | low | >=6.1.0 <6.1.3 |
| postcss-selector-parser | [GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) | moderate | <7.1.6 |
| sharp | [GHSA-f88m-g3jw-g9cj](https://github.com/advisories/GHSA-f88m-g3jw-g9cj) | high | <0.35.0 |
| sharp | [GHSA-rgj7-g3m4-5g8c](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c) | high | <0.35.4 |
| sharp | [GHSA-wq5f-xc86-pv6w](https://github.com/advisories/GHSA-wq5f-xc86-pv6w) | high | <0.35.5 |
| source-map-js | [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) | high | >=1.0.0 <1.2.2 |
