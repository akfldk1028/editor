# GitAgent Runtime Provenance

- Upstream: `https://github.com/open-gitagent/gitagent.git`
- Snapshot commit: `d3e25d746e55b3a1f1794f906bce7745c9fe1ef1`
- Package version: `2.0.2`
- Ownership: generic runtime only; PLANM and DWG product code are forbidden.

This vendored snapshot intentionally excludes upstream `.git`, `node_modules`,
and `dist`. `package.json` and `package-lock.json` include the 2026-08-06
security dependency refresh that produced zero npm audit vulnerabilities and
passed the upstream TypeScript build and 70-test suite before extraction.

Future updates must record a reviewed upstream commit and re-run the runtime
boundary, build, audit, and upstream test suites.
