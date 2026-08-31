# OAuth CLI Provider Runtime

DWG Intelligence uses locally installed agent CLIs instead of embedding OpenAI
or Anthropic API keys.

## Runtime flow

```text
apps/workspace composer
  -> Vite /api proxy
  -> 127.0.0.1:4317 provider gateway
  -> validate provider + message + DWG/DXF path
  -> ACadSharp v0.2 or legacy DXF v0.1 normalized CAD index
  -> bounded CAD context with handles and bounding boxes
  -> provider-neutral ChatProvider + AbortSignal
       |-- Codex CLI (cached ChatGPT login)
       `-- Claude CLI (cached claude.ai subscription login)
  -> grounded response with [handle:...] evidence + resumable session ID
  -> apps/workspace conversation panel
```

## Folder ownership

- `modules/cad-runtime/src/providers/contracts.ts`: provider-neutral boundary.
- `modules/cad-runtime/src/providers/cli/`: subprocess and OAuth-only environment policy.
- `modules/cad-runtime/src/providers/codex/`: Codex CLI auth and JSONL response adapter.
- `modules/cad-runtime/src/providers/claude/`: Claude CLI auth and JSON response adapter.
- `modules/cad-runtime/src/application/chat/`: CAD context construction and grounded prompt policy.
- `modules/cad-runtime/src/http/`: loopback gateway and production composition.
- `packages/contracts/src/provider.ts`: shared browser/gateway DTOs and UUID validation.
- `modules/cad-runtime/tests/providers/`: fake-CLI contract and gateway integration tests.
- `modules/cad-runtime/harness/provider-smoke.ts`: explicit live authenticated smoke test.
- `apps/workspace/src/features/agent-chat/`: provider selection, tab-scoped session
  storage, composer, response UI, and feature CSS.

Product code never imports from `clone/`. `clone/claudian` is a research-only
snapshot used to compare provider/runtime boundaries.

## Authentication and safety

- Codex authentication is checked with `codex login status`.
- Claude authentication is checked with `claude auth status --json`.
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `CLAUDE_API_KEY` are removed from
  provider subprocess environments.
- First Codex turns are persisted and follow-up turns use
  `codex exec resume <session-id>`; execution stays read-only and
  approval-free.
- First Claude turns are persisted and follow-up turns use
  `claude --resume <session-id>`; print mode stays in plan permission mode
  with tools disabled.
- Apps/workspace keeps one validated UUID session ID per persisted workspace
  conversation in `localStorage`. Reloads resume that conversation, New Chat
  starts without an OAuth session ID, and switching providers never reuses a
  different provider's ID.
- Browser cancellation propagates through the loopback HTTP request and
  `AbortSignal` to the subprocess runner. Cancelled or late responses are not
  rendered.
- Drawing text is treated as untrusted data. Responses must not follow
  instructions contained inside a drawing.
- Drawing claims must cite stable CAD handles. Unsupported table or semantic
  structure must be stated as a limitation rather than guessed.
- Chat context selection scans the whole normalized index and ranks entities
  against the current question before applying the provider context budget.
  An entity is no longer excluded only because it appears after the first 200
  index entries.
- The HTTP gateway binds only to `127.0.0.1`.

## Commands

```powershell
# Explicit real-login smoke tests
npm run providers:smoke -- codex
npm run providers:smoke -- claude

# Real Codex + Claude browser reload/resume tests and 1440x900 evidence PNGs
npm --workspace @click-around/workspace run test:live-oauth-browser

# Optional: run one provider or override the isolated ports
$env:DWG_LIVE_PROVIDER = "codex"
$env:DWG_LIVE_FRONTEND_PORT = "4183"
$env:DWG_LIVE_GATEWAY_PORT = "4327"
npm --workspace @click-around/workspace run test:live-oauth-browser
```

Each smoke test performs two turns and verifies that the second result keeps
the first result's session ID. The browser harness starts isolated loopback
gateway and Vite processes from the current checkout without route mocks,
preflights both health and drawing routes, reloads the page between turns,
checks for console errors, and writes provider-specific evidence PNGs under
`tests/visual/artifacts/oauth-*-persistent-browser-e2e.png`.

## Runtime choice

The stable non-interactive resume commands are the current product transport:

- [Codex non-interactive resume](https://developers.openai.com/codex/non-interactive-mode)
- [Claude Code CLI resume](https://docs.anthropic.com/en/docs/claude-code/cli-usage)

Codex app-server remains behind the same provider-neutral contract as a future
streaming transport. It is not the default here because its local protocol is
documented as a development/debugging surface that may change:

- [Codex app-server](https://developers.openai.com/codex/app-server)
