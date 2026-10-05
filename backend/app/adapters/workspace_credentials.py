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


def apply_environment(component, environment):
    """Return a deep copy with empty model credential fields filled from saved settings."""
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
        fields = MODEL_CREDENTIAL_FIELDS.get(value.get("provider"))
        if fields and value.get("component_type") == "model":
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
