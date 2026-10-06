import copy


# Saved workspace settings feed model clients at load time only. The process
# environment is never written: the SDKs already read their own variables when a
# field is absent, so an explicit template value wins, then a saved setting.
MODEL_CREDENTIAL_FIELDS = {
    "autogen_ext.models.openai.OpenAIChatCompletionClient": {
        "api_key": "OPENAI_API_KEY",
        "base_url": "OPENAI_BASE_URL",
    },
    "autogen_ext.models.openai.AzureOpenAIChatCompletionClient": {
        "api_key": "AZURE_OPENAI_API_KEY",
        "azure_endpoint": "AZURE_OPENAI_ENDPOINT",
    },
    "autogen_ext.models.anthropic.AnthropicChatCompletionClient": {
        "api_key": "ANTHROPIC_API_KEY",
    },
    "autogen_ext.models.ollama.OllamaChatCompletionClient": {
        "host": "OLLAMA_HOST",
    },
}


# Hosted providers whose key-less model components run on the local Claude Code login in oauth
# mode (core.model_auth). Ollama is local already and keeps its own client.
OAUTH_REPLACED = frozenset({
    "autogen_ext.models.openai.OpenAIChatCompletionClient",
    "autogen_ext.models.openai.AzureOpenAIChatCompletionClient",
    "autogen_ext.models.anthropic.AnthropicChatCompletionClient",
})


def apply_environment(component, environment, mode="api_key"):
    """Return a deep copy ready to load.

    api_key (deployment): empty model credential fields are filled from saved settings.
    oauth (local development): a hosted model without an explicit key in the template runs on the
    developer's Claude Code CLI login instead; a template that names its own key keeps it.
    """
    if mode not in ("api_key", "oauth"):
        raise ValueError("model auth mode must be api_key or oauth")
    if mode == "oauth":
        component = copy.deepcopy(component)
        _to_cli(component)
        return component
    values = {
        item["name"]: item["value"]
        for item in environment
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("value"), str)
        and item["value"] != ""
    }
    component = copy.deepcopy(component)
    if values:
        _fill(component, values)
    return component


def _fill(value, values):
    if isinstance(value, dict):
        # The provider alone identifies a model client; component_type is optional in autogen.
        fields = MODEL_CREDENTIAL_FIELDS.get(value.get("provider"))
        if fields:
            config = value.setdefault("config", {})
            if isinstance(config, dict):
                for field, name in fields.items():
                    if config.get(field) in (None, "") and name in values:
                        config[field] = values[name]
        for child in value.values():
            _fill(child, values)
    elif isinstance(value, list):
        for child in value:
            _fill(child, values)


def _to_cli(value):
    from backend.app.adapters.cli_model_client import PROVIDER
    if isinstance(value, dict):
        config = value.get("config")
        if value.get("provider") in OAUTH_REPLACED and isinstance(config, dict) and config.get("api_key") in (None, ""):
            model = config.get("model")
            claude = model if value["provider"].endswith("AnthropicChatCompletionClient") else None
            value["provider"] = PROVIDER
            value["component_type"] = "model"
            value["version"] = value["component_version"] = 1
            value["description"] = f"{model or 'model'} on the local Claude Code login (EDITOR_MODEL_AUTH=oauth)"
            value["config"] = {"model": claude} if claude else {}
            return
        for child in value.values():
            _to_cli(child)
    elif isinstance(value, list):
        for child in value:
            _to_cli(child)
