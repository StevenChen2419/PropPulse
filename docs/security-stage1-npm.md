# Stage 1 npm dependency verification

Verified October 23, 2026 using Node 24.22.1 and npm 11.19.1. No frontend package versions or lockfile changes were necessary or made. Keep using `npm ci` with the existing `frontend/package-lock.json`; it is the single frontend lock mechanism.

## Current findings and disposition

- Both initial and final `npm audit --omit=dev --json`: **0 findings**.
- Both initial and final full `npm audit --json`: **3 moderate package entries, representing one advisory**, [GHSA-rj75-hqrm-r3gf / CVE-2026-104844](https://github.com/advisories/GHSA-rj75-hqrm-r3gf).
- Installed dependency path: direct development dependency `tailwindcss@3.4.19` and transitive `postcss-nested@6.2.0` use `postcss-selector-parser@6.1.4`. Affected parser versions are `<7.1.6`; the fixed version is `7.1.6`. The Tailwind and nested entries propagate the same parser advisory and are not additional vulnerabilities.
- The advisory concerns CPU exhaustion parsing attacker-controlled CSS selectors. Tailwind/PostCSS compile repository source at build time; no application source imports these parsers or exposes a CSS compilation endpoint. This remains an installed development/build vulnerability, not a verified production request-path exposure. Build only trusted source; do not expose the development server or compile untrusted submitted CSS.
- The npm registry confirms `3.4.19` is the newest Tailwind v3 release. Its declared parser range is `^6.1.2`, and nested's range is also v6. No compatible patch/minor resolution currently reaches parser `7.1.6`. npm's offered remediation is Tailwind `4.3.3`, a major upgrade. Defer this finding until an upstream v3-compatible fix or a separately verified Tailwind v4 migration. No forced audit fixes or new transitive overrides were introduced. The existing Next/PostCSS override is unchanged.

Registry evidence commands: `npm view tailwindcss@3 version --json`, `npm view tailwindcss@3.4.19 dependencies.postcss-selector-parser dependencies.postcss-nested --json`, and `npm view postcss-nested@6 dependencies.postcss-selector-parser --json`.

## Verification

- Clean `npm ci --ignore-scripts --no-audit`: installed 148 packages successfully from the existing lockfile. Lifecycle scripts were disabled for this validation; the subsequent production build verified the resulting install. `npm ls --depth=0` exited successfully.
- Relevant final versions: Next `15.5.28`, React/React DOM `19.0.9`, PostCSS `8.5.30`, Tailwind `3.4.19`, autoprefixer `10.5.0`, TypeScript `5.9.3`, Playwright `1.64.1`.
- `npm test`: **116 passed**, zero failures/skips.
- `npx tsc --noEmit`: passed.
- `npm run build`: passed, including static page generation.
- Chrome production-build smoke: **4 passed** using the existing offline fixture tests for saved selection/slip editing at 390/768/1440 pixels and temporary failure/authentication/slip recovery. All backend traffic was mocked by those tests; no database or sports-provider calls were made. Ran `PLAYWRIGHT_EXTERNAL_SERVER=1 npx playwright test e2e/ui-polish.spec.cjs e2e/saved-selections.spec.cjs` against a separately started local production frontend. The default Playwright-owned Windows server teardown hung after all assertions passed; external-server mode exited successfully and the local server was stopped.
- Final full and production audits ran after the clean install and build; results remained as above. Registry audits required network-enabled execution because the sandbox blocks registry traffic.

No new frontend runtime regression was observed. The existing untracked `frontend/.node-version` was not edited. The full browser suite and frontend/backend database integration browser suite were not run for this dependency-only frontend review; the focused production smoke covered persistence and styling-sensitive workflows without touching development data. Public deployment remains unapproved.
