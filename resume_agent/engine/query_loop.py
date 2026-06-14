from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from resume_agent.engine.hooks import run_post_tool_hooks
from resume_agent.engine.trace import TraceLogger
from resume_agent.model.openai_client import ChatModelClient, ModelResponse
from resume_agent.tools.base import ToolContext, ToolPermission, ToolResult
from resume_agent.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: Mapping


@dataclass
class QueryLoopResult:
    tool_results: list[ToolResult] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    final_message: str = ""
    turns: int = 0


def run_tool_plan(
    registry: ToolRegistry,
    calls: list[ToolCall],
    context: ToolContext,
    allowed_permissions: set[ToolPermission],
    trace: TraceLogger | None = None,
) -> QueryLoopResult:
    result = QueryLoopResult()
    for call in calls:
        _execute_tool_with_hooks(
            result=result,
            registry=registry,
            name=call.name,
            input_data=call.input,
            context=context,
            allowed_permissions=set(allowed_permissions),
            trace=trace,
        )
    return result


def run_agent_loop(
    model_client: ChatModelClient,
    registry: ToolRegistry,
    messages: list[dict[str, Any]],
    context: ToolContext,
    allowed_permissions: set[ToolPermission],
    trace: TraceLogger | None = None,
    max_turns: int = 12,
) -> QueryLoopResult:
    result = QueryLoopResult()
    active_messages = list(messages)
    tools = registry.model_schemas(allowed_permissions)

    for turn in range(1, max_turns + 1):
        if trace:
            trace.record("model_turn", {"turn": turn, "message_count": len(active_messages), "tool_count": len(tools)})
        model_response = model_client.complete(list(active_messages), tools)
        result.turns = turn
        active_messages.append(_assistant_message(model_response))

        if not model_response.tool_calls:
            result.final_message = model_response.content
            return result

        for call in model_response.tool_calls:
            tool_result = _execute_tool_with_hooks(
                result=result,
                registry=registry,
                name=call.name,
                input_data=call.input,
                context=context,
                allowed_permissions=set(allowed_permissions),
                trace=trace,
                tool_call_id=call.id,
            )
            tool_content = _tool_content(tool_result)
            active_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": tool_content,
                }
            )

    raise RuntimeError(f"agent loop exceeded max_turns={max_turns}")


def _execute_tool_with_hooks(
    result: QueryLoopResult,
    registry: ToolRegistry,
    name: str,
    input_data: Mapping,
    context: ToolContext,
    allowed_permissions: set[ToolPermission],
    trace: TraceLogger | None = None,
    tool_call_id: str | None = None,
) -> ToolResult:
    call_payload: dict[str, Any] = {"name": name, "input": dict(input_data)}
    if tool_call_id:
        call_payload["tool_call_id"] = tool_call_id
    if trace:
        trace.record("tool_call", call_payload)
    tool_result = registry.execute(name, input_data, context, allowed_permissions)
    result.tool_results.append(tool_result)
    result.changed_files.extend(_output_paths(tool_result))
    result_payload: dict[str, Any] = {"name": name, "result": tool_result.content}
    if tool_call_id:
        result_payload["tool_call_id"] = tool_call_id
    if trace:
        trace.record("tool_result", result_payload)

    hook_result = run_post_tool_hooks(
        tool_name=name,
        original_input=input_data,
        registry=registry,
        context=context,
        allowed_permissions=allowed_permissions,
        trace=trace,
    )
    result.warnings.extend(hook_result.warnings)
    for item in hook_result.tool_results:
        result.tool_results.append(item)
        result.changed_files.extend(_output_paths(item))
    return tool_result


def _output_paths(result: ToolResult) -> list[str]:
    if not isinstance(result.content, dict):
        return []
    outputs = result.content.get("outputs", {})
    if not isinstance(outputs, dict):
        return []
    return [str(value) for value in outputs.values()]


def _assistant_message(response: ModelResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.input, ensure_ascii=False),
                },
            }
            for call in response.tool_calls
        ]
    return message


def _tool_content(result: ToolResult) -> str:
    try:
        return json.dumps(result.content, ensure_ascii=False)
    except TypeError:
        return str(result.content)
