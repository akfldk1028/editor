# AutoGen workspace and model access (2026-10-06)

## What was absorbed from AutoGen Studio (AG)
- Saved settings keys → model clients at load time (`adapters/workspace_credentials.py`,
  deep copy, never `os.environ`); tool policy `adapters/workspace_tool_policy.py`
  (FunctionTool/code/stdio refused; Static(Stream)Workbench, editor tools, HTTP MCP allowed).
- `POST /api/v1/workspace/validate/test` (gallery "Test") → `modules/workspace/component_test.py`.
- Seeds (`modules/workspace/seeds.py`, marker table — a deleted seed is not revived).
- Replay client is a supported provider (deterministic tests).
- `/law` AI deep analysis: `GET /api/v1/land/agent-analyze/stream` (SSE) →
  `modules/land/agent_analysis.py`; Land team = land_analyst + legal_interpreter + report_writer.

## Model auth: local OAuth, API keys only in deployment (user decision 2026-10-06)
`EDITOR_MODEL_AUTH` (owner `app/core/model_auth.py`): `oauth` | `api_key`. Unset → `oauth` when
the `claude` CLI is on PATH, else `api_key`. Deployment compose (`infra/docker/compose.yml`)
sets `api_key`.
- oauth: a hosted model component **without** an explicit key in the template runs on the
  developer's Claude Code login via `adapters/cli_model_client.py`
  (`ClaudeCodeChatCompletionClient`: one headless `claude -p --output-format json --tools ""
  --setting-sources "" --strict-mcp-config --system-prompt-file`, agent tools as `--json-schema`
  structured output → FunctionCall). A template that names its own key keeps it.
- The child process must not see `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` (a placeholder key
  would replace the login) — stripped in `_run_cli`.
- Verified live: gallery test answered "4"; `/law` deep analysis ran 3 agents with tools to a
  full report (121 s) with no API key.
- The stored OpenAI key has **no credits** (credit_balance_exhausted); the Anthropic key is a
  3-character placeholder. Do not "fix" by adding keys locally — use oauth.

## Tests
`backend/tests/conftest.py` pins `EDITOR_MODEL_AUTH=api_key` for the whole suite (otherwise a
dev machine would call the real CLI). `test_model_auth_oauth.py` covers the switch and client.
