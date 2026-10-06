from backend.app.core.mcp_params import validate_params


# Tool and workbench components a saved template may load. Everything else that
# can run code or spawn a process on this host is named here so the refusal says
# why instead of "unsupported".
CONTAINER_PROVIDERS = frozenset(
    {
        "autogen_core.tools.StaticWorkbench",
        "autogen_core.tools.StaticStreamWorkbench",
    }
)

EDITOR_TOOL_PROVIDERS = frozenset(
    {
        "backend.app.adapters.workspace_tools.LandAnalyzeTool",
        "backend.app.adapters.workspace_tools.LawSearchTool",
    }
)

MCP_PROVIDERS = frozenset(
    {
        "autogen_ext.tools.mcp.McpWorkbench",
        "autogen_ext.tools.mcp.SseMcpToolAdapter",
        "autogen_ext.tools.mcp.StreamableHttpMcpToolAdapter",
    }
)

REJECTED_PREFIXES = (
    ("autogen_core.tools.FunctionTool", "FunctionTool executes stored source code"),
    ("autogen_ext.tools.code_execution", "Code execution tools run on this host"),
    ("autogen_ext.code_executors", "Code executors run on this host"),
    ("autogen_ext.tools.http.HttpTool", "HttpTool is not supported in templates"),
    ("autogen_ext.tools.mcp.StdioMcpToolAdapter", "Stdio MCP tools spawn a process"),
    ("autogen_ext.agents.web_surfer", "Browser agents are not supported in templates"),
)


def check_tool_component(component):
    """True when this module allows the component, False when it is not a tool concern.

    Raises ValueError for components that are known to be unsafe to load from a
    stored template.
    """
    provider = component.get("provider")
    if provider in CONTAINER_PROVIDERS or provider in EDITOR_TOOL_PROVIDERS:
        return True
    if provider in MCP_PROVIDERS:
        config = component.get("config")
        params = config.get("server_params") if isinstance(config, dict) else None
        if not isinstance(params, dict):
            raise ValueError("MCP template components require server_params")
        validate_params(params)
        if params.get("type") == "StdioServerParams":
            raise ValueError("Template MCP tools must use an HTTP transport")
        return True
    for prefix, reason in REJECTED_PREFIXES:
        if isinstance(provider, str) and provider.startswith(prefix):
            raise ValueError(f"Unsupported executable team component: {reason}")
    return False
