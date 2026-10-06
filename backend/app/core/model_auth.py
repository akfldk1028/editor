"""One owner for how workspace model clients authenticate.

EDITOR_MODEL_AUTH
  oauth    local development: model calls go through the Claude Code CLI the developer is
           already logged into (subscription OAuth); no API key is read or needed.
  api_key  deployment: the provider SDKs run with the keys saved in workspace settings.

Unset means oauth when the `claude` CLI is on PATH (a developer machine) and api_key
otherwise (a container has no CLI login). Deployment compose files set it explicitly.
"""
import os
import shutil

ENV = 'EDITOR_MODEL_AUTH'
MODES = frozenset({'oauth', 'api_key'})


def model_auth_mode(env=os.environ, which=shutil.which):
    value = str(env.get(ENV) or '').strip().lower()
    if value:
        if value not in MODES:
            raise ValueError(f'{ENV} must be one of {sorted(MODES)}')
        return value
    return 'oauth' if which('claude') else 'api_key'
