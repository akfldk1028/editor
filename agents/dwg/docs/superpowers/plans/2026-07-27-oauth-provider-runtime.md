# OAuth CLI Provider Runtime Plan

**Goal:** Let the DWG workspace use the user's existing Codex ChatGPT login or Claude subscription login without requiring application API keys.

**Architecture:** A provider-neutral chat service owns CAD context preparation and delegates generation to isolated CLI adapters. Codex uses the local CLI's authenticated non-interactive surface first, behind a transport interface compatible with later app-server streaming. Claude uses its local authenticated print mode. A localhost-only gateway exposes provider status and chat to the Vite UI. Tests substitute fake process runners; live smoke tests explicitly verify both installed authenticated CLIs.

**Reference:** Claudian separates `ChatRuntime` from Codex app-server and Claude SDK implementations. DWG Intelligence follows the same dependency direction without importing code from `clone/`.

## Module layout

```text
agent/src/
|-- providers/
|   |-- contracts.ts
|   |-- cli/
|   |   |-- processRunner.ts
|   |   `-- oauthEnvironment.ts
|   |-- codex/
|   |   |-- codexAuth.ts
|   |   `-- codexCliProvider.ts
|   |-- claude/
|   |   |-- claudeAuth.ts
|   |   `-- claudeCliProvider.ts
|   `-- providerRegistry.ts
|-- application/chat/
|   |-- cadContextBuilder.ts
|   `-- chatService.ts
`-- http/providerGateway.ts
```

## Task 1: Provider contracts and OAuth-only process boundary

- Define provider status, chat request/result, runtime, event, and process-runner contracts.
- Remove `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from provider subprocess environments so cached CLI login is the active credential source.
- Test command construction, credential stripping, timeout, stderr handling, and output parsing with fake runners.

## Task 2: Codex and Claude CLI adapters

- Detect Codex with `codex login status`; detect Claude with `claude auth status --json`.
- Codex runs read-only, approval-free, ephemeral `codex exec --json` turns.
- Claude runs read-only `claude --print --output-format json --permission-mode plan --tools ""`.
- Normalize both results into one provider-neutral response and retain provider session IDs when returned.

## Task 3: CAD-grounded chat service and local gateway

- Open and index the requested real DWG through the existing CAD runtime.
- Build a bounded structural context containing source, counts, layers, text, blocks, types, handles, and bounding boxes.
- Require the provider to state limitations and cite CAD handles for drawing claims.
- Serve `GET /api/providers`, `POST /api/chat`, and `GET /api/health` on loopback only.
- Validate payload size, provider ID, file extension, and local file existence before invoking a model.

## Task 4: Provider-aware frontend

- Replace the decorative composer with controlled input, Codex/Claude selector, authenticated status, submit/cancel state, and rendered response.
- Keep the deterministic scenario controls for visual regression.
- Proxy `/api` to the local gateway in development.

## Task 5: Verification loop

- Run provider unit/integration tests with fake CLIs.
- Run live authenticated smoke prompts against Codex and Claude.
- Start gateway and frontend together; verify provider statuses and one real-DWG grounded response.
- Run Playwright semantic checks and regenerate/inspect provider-connected PNGs.
- Re-run Node, MCP, orchestration, DWG, frontend build, and .NET tests before merging.
