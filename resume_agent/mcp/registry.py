"""Convert MCP server tools into FunctionTool objects for the agent's ToolRegistry.

Every tool discovered from an MCP server becomes a FunctionTool whose handler
opens a fresh stdio connection, calls ``tools/call``, and returns the result.
Connection pooling (keep-alive across calls) is a future optimisation — for
the current single-server / low-throughput usage pattern the overhead of a new
subprocess per call is negligible.
"""

from __future__ import annotations

from typing import Any, Mapping

from resume_agent.mcp.client import StdioMCPClient
from resume_agent.mcp.config import StdioMCPServerConfig, load_mcp_config
from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission


def load_mcp_tools(repo_root: str | None = None) -> list[FunctionTool]:
    """Discover tools from all configured MCP servers and return them as FunctionTool objects.

    Each tool is permission-gated as ``ToolPermission.NETWORK`` because external
    MCP servers are treated as network-adjacent — the CLI must pass ``--allow-network``
    for them to appear in the model's available-tool list.
    """
    from pathlib import Path

    root = Path(repo_root) if repo_root else Path.cwd()
    config = load_mcp_config(root)

    tools: list[FunctionTool] = []
    for server_cfg in config.servers:
        try:
            server_tools = _discover_server_tools(server_cfg)
        except ToolExecutionError as exc:
            # A misconfigured / unreachable server is not fatal — skip it and
            # let the other servers' tools register.
            print(f"[mcp] skipping server {server_cfg.name}: {exc}")
            server_tools = []
        tools.extend(server_tools)

    return tools


def _discover_server_tools(cfg: StdioMCPServerConfig) -> list[FunctionTool]:
    """Connect to one MCP server, list its tools, and convert them."""
    with StdioMCPClient(cfg) as client:
        client.initialize()
        raw_tools = client.list_tools()

    return [_mcp_tool_to_function_tool(raw, cfg) for raw in raw_tools]


def _mcp_tool_to_function_tool(
    raw: Mapping[str, Any],
    server_cfg: StdioMCPServerConfig,
) -> FunctionTool:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ToolExecutionError(f"MCP server {server_cfg.name} returned a tool without a name")

    # Prefix with server name to avoid collisions with built-in tools.
    # E.g. a Firecrawl server's "search" becomes "mcp/firecrawl/search".
    qualified = f"mcp/{server_cfg.name}/{name}"

    description = str(raw.get("description") or f"MCP tool {name} from {server_cfg.name}")
    input_schema = _normalise_schema(raw.get("inputSchema"))

    handler = _make_mcp_tool_handler(server_cfg, name)

    return FunctionTool(
        name=qualified,
        description=description,
        input_schema=input_schema,
        read_only=False,  # MCP tools are opaque — assume they may have side effects
        permission=ToolPermission.NETWORK,
        handler=handler,
    )


def _make_mcp_tool_handler(
    server_cfg: StdioMCPServerConfig,
    tool_name: str,
):
    """Return a handler that opens a fresh connection, calls the tool, and tears down."""

    def handler(input_data: Mapping[str, Any], context) -> Any:
        with StdioMCPClient(server_cfg) as client:
            client.initialize()
            result = client.call_tool(tool_name, dict(input_data))
        return result

    return handler


def _normalise_schema(raw_schema: Any) -> dict[str, Any]:
    """Ensure the input schema is at minimum a JSON Schema object."""
    if isinstance(raw_schema, Mapping):
        schema = dict(raw_schema)
    else:
        schema = {}
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {}}
    schema.setdefault("properties", {})
    return schema
