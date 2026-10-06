import base64
import io
import asyncio

from backend.app.adapters.workspace_credentials import apply_environment
from backend.app.core.model_auth import model_auth_mode
from backend.app.adapters.workspace_tool_policy import check_tool_component


TEXT_ATTACHMENT_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/typescript",
        "application/x-yaml",
        "application/yaml",
        "application/csv",
        "application/x-python",
    }
)


SUPPORTED_PROVIDERS = frozenset(
    {
        "autogen_agentchat.teams.RoundRobinGroupChat",
        "autogen_agentchat.teams.SelectorGroupChat",
        "autogen_agentchat.teams.Swarm",
        "autogen_agentchat.agents.AssistantAgent",
        "autogen_agentchat.agents.UserProxyAgent",
        "autogen_agentchat.conditions.MaxMessageTermination",
        "autogen_agentchat.conditions.TextMentionTermination",
        "autogen_agentchat.conditions.TimeoutTermination",
        "autogen_agentchat.conditions.StopMessageTermination",
        "autogen_agentchat.conditions.TokenUsageTermination",
        "autogen_agentchat.conditions.HandoffTermination",
        "autogen_agentchat.conditions.SourceMatchTermination",
        "autogen_agentchat.conditions.TextMessageTermination",
        "autogen_agentchat.base.OrTerminationCondition",
        "autogen_agentchat.base.AndTerminationCondition",
        "autogen_ext.models.openai.OpenAIChatCompletionClient",
        "autogen_ext.models.openai.AzureOpenAIChatCompletionClient",
        "autogen_ext.models.anthropic.AnthropicChatCompletionClient",
        "autogen_ext.models.ollama.OllamaChatCompletionClient",
        # Scripted replies, no network: demos and execution tests without a key.
        "autogen_ext.models.replay.ReplayChatCompletionClient",
        # Local development: hosted models run on the developer's Claude Code login (core.model_auth).
        "backend.app.adapters.cli_model_client.ClaudeCodeChatCompletionClient",
        "autogen_core.model_context.UnboundedChatCompletionContext",
        "autogen_core.model_context.BufferedChatCompletionContext",
        "autogen_core.model_context.HeadAndTailChatCompletionContext",
    }
)


def validate_components(value):
    # An installed namespace also contains host executors and stdio tool loaders.
    # Saved template loading permits only these non-executable component classes.
    if isinstance(value, dict):
        provider = value.get("provider")
        if provider is not None:
            if not isinstance(provider, str):
                raise ValueError(UNSUPPORTED)
            if provider not in SUPPORTED_PROVIDERS:
                if not check_tool_component(value):
                    raise ValueError(UNSUPPORTED)
                # A tool container or MCP workbench: its own tool schemas carry no
                # provider, so only the nested components are checked.
                config = value.get("config")
                if isinstance(config, dict):
                    validate_components(config.get("tools", []))
                    validate_components(config.get("model_client"))
                return
        for child in value.values():
            validate_components(child)
    elif isinstance(value, list):
        for child in value:
            validate_components(child)


UNSUPPORTED = "Unsupported executable team component; check /runs/capabilities. Code, browser and stdio MCP components require their explicit isolated execution integration"


def load_team(component, input_callback, environment=()):
    from autogen_agentchat.base import Team
    from autogen_agentchat.agents import UserProxyAgent

    component = apply_environment(component, environment, model_auth_mode())
    validate_components(component)
    team = Team.load_component(component)

    def attach(participants):
        for participant in participants:
            if isinstance(participant, UserProxyAgent):
                participant.input_func = input_callback
                participant._is_async = True
            elif isinstance(participant, Team):
                attach(participant._participants)

    attach(team._participants)
    return team


async def close_team(team):
    resources = {}

    def collect(component):
        client = getattr(component, "_model_client", None)
        if client is not None:
            resources[id(client)] = client
        for child in getattr(component, "_participants", []):
            collect(child)
            if hasattr(child, "close"):
                resources[id(child)] = child

    collect(team)
    for resource in resources.values():
        try:
            await asyncio.wait_for(resource.close(), timeout=5)
        except Exception:
            pass


def make_task(text, files):
    from autogen_agentchat.messages import MultiModalMessage
    from autogen_core import Image
    from PIL import Image as PILImage

    content = [text]
    for file in files:
        raw = base64.b64decode(file["content"], validate=True)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Attachment exceeds 8 MB")
        if file["type"].startswith("image/"):
            with PILImage.open(io.BytesIO(raw)) as image:
                content.append(Image(image.copy()))
        elif file["type"].startswith("text/") or file["type"] in TEXT_ATTACHMENT_TYPES:
            content.append(f"\nAttachment: {file['name']}\n{raw.decode('utf-8')}")
        else:
            raise ValueError("Attachment must be a UTF-8 text file or image")
    return text if not files else MultiModalMessage(source="user", content=content)
