# Embed DWG Intelligence as one folder

Use a Git submodule when a broader repository should consume this project while
preserving its history, boundaries, tests, and repository-owned memory.

## Add it to a host repository

From the host repository root:

```powershell
git submodule add https://github.com/akfldk1028/DWG.git vendor/dwg-intelligence
git submodule update --init --recursive
npm --prefix vendor/dwg-intelligence ci
npm --prefix vendor/dwg-intelligence run verify
```

The host records an exact DWG Intelligence commit. Review and merge changes in
this repository first, then deliberately advance that recorded commit in the
host; do not silently track an unreviewed branch tip.

## Choose one integration boundary

Prefer a process boundary for the broadest isolation:

- Loopback API: `npm --prefix vendor/dwg-intelligence run gateway`
- MCP stdio: configure the client command as `npm` (or `npm.cmd` on Windows)
  with arguments `--prefix`, `vendor/dwg-intelligence`, `run`, `mcp`.
- Full UI: run the workspace only as the complete composition; do not import
  individual feature folders.

For contract-only use, declare a `file:` dependency whose path is relative to
the consuming package, for example:

```json
{
  "dependencies": {
    "@dwg/contracts": "file:../../vendor/dwg-intelligence/packages/contracts"
  }
}
```

Adjust the relative prefix for the host layout and keep the package's declared
dependencies. The authoritative options and compatibility rules are in
[`../architecture/integration-contract.md`](../architecture/integration-contract.md).

## Give host agents the right context

Add a short rule to the host repository's `AGENTS.md` (and equivalent agent
entry points):

```markdown
Before changing `vendor/dwg-intelligence`, read
`vendor/dwg-intelligence/AGENTS.md` and
`vendor/dwg-intelligence/docs/handoff/repo-memory.md`. Treat that folder as an
independently versioned repository and use only its supported integration
surfaces.
```

Do not copy local `.claude`, `.codex`, `.remember`, environment, OAuth, or
drawing files into the submodule.

## Update later

```powershell
git -C vendor/dwg-intelligence fetch origin
git -C vendor/dwg-intelligence checkout <reviewed-commit>
git add vendor/dwg-intelligence
git commit -m "chore: update DWG Intelligence submodule"
```

Run the DWG repository verification before committing the host's new submodule
pointer.
