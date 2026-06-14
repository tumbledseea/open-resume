from __future__ import annotations

import json
import subprocess
from itertools import count
from typing import Any, Mapping

from resume_agent.mcp.config import StdioMCPServerConfig
from resume_agent.tools.base import ToolExecutionError


class StdioMCPClient:
    """Minimal stdio JSON-RPC client for local MCP servers."""

    def __init__(self, config: StdioMCPServerConfig) -> None:
        self.config = config
        self._ids = count(1)
        self._process: subprocess.Popen[str] | None = None

    def __enter__(self) -> StdioMCPClient:
        env = None
        if self.config.env:
            import os

            env = dict(os.environ)
            env.update(self.config.env)
        self._process = subprocess.Popen(
            [self.config.command, *self.config.args],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        return self

    def __exit__(self, *args: object) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._process = None

    def initialize(self) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "openresume", "version": "0.1.0"},
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, Mapping) else []
        return [dict(tool) for tool in tools if isinstance(tool, Mapping)]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": dict(arguments)})

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        process = self._require_process()
        assert process.stdin is not None
        assert process.stdout is not None

        request_id = next(self._ids)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

        while True:
            line = process.stdout.readline()
            if not line:
                raise ToolExecutionError(f"MCP server {self.config.name} closed stdout")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != request_id:
                continue
            if response.get("error"):
                raise ToolExecutionError(f"MCP {method} failed: {response['error']}")
            result = response.get("result", {})
            return dict(result) if isinstance(result, Mapping) else {"result": result}

    def _require_process(self) -> subprocess.Popen[str]:
        if self._process is None:
            raise ToolExecutionError("MCP client is not started")
        return self._process
