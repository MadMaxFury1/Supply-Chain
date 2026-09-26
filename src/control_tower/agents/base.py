"""Shared LLM tool-calling harness.

Two tool dispatchers implement the same small interface:

- `StdioToolDispatcher` - production. Spawns each MCP server as its own
  subprocess and talks to it over the real MCP stdio protocol, per
  CLAUDE.md Principle 2 ("enterprise capabilities exposed through typed
  MCP tools").
- `InProcessToolDispatcher` - tests. Calls the same server objects'
  `call_tool`/`list_tools` in-process (no subprocess), so agent-behavior
  tests exercise the real tool + guardrail code without process overhead.

Which tools an agent is even offered (see each agent module) is the
least-privilege boundary; the write tools additionally re-check
authorization themselves at execution time (Guardrail Gate B), so a
misbehaving agent can't just call them out of turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from control_tower.config import ANTHROPIC_MODEL

SRC_DIR = Path(__file__).resolve().parents[2]

MCP_SERVER_MODULES = {
    "inventory": "control_tower.mcp_servers.inventory_server",
    "supplier": "control_tower.mcp_servers.supplier_server",
    "manufacturing": "control_tower.mcp_servers.manufacturing_server",
    "workflow_audit": "control_tower.mcp_servers.workflow_audit_server",
}


class MCPToolError(RuntimeError):
    """Raised uniformly by both dispatchers on tool failure or guardrail denial."""


@dataclass
class ToolSpec:
    server_key: str
    name: str
    description: str
    input_schema: dict


class ToolDispatcher(Protocol):
    async def list_tools(self, server_key: str) -> list[ToolSpec]: ...
    async def call(self, server_key: str, tool_name: str, arguments: dict) -> Any: ...


def _unwrap_call_result(result) -> Any:
    if result.is_error:
        text = "; ".join(getattr(b, "text", "") for b in (result.content or []))
        raise MCPToolError(text or "tool call failed")
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        # Tools returning a list (or other non-object type) get their MCP
        # structured output wrapped as {"result": [...]} since the protocol
        # requires structured content to be a JSON object - unwrap it back
        # to the plain value callers actually expect.
        if isinstance(structured, dict) and structured.keys() == {"result"}:
            return structured["result"]
        return structured
    texts = [getattr(b, "text", "") for b in (result.content or [])]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


class InProcessToolDispatcher:
    """Calls MCP server objects directly in this process - for tests."""

    def __init__(self):
        from control_tower.mcp_servers import (
            inventory_server,
            manufacturing_server,
            supplier_server,
            workflow_audit_server,
        )

        self._servers = {
            "inventory": inventory_server.server,
            "supplier": supplier_server.server,
            "manufacturing": manufacturing_server.server,
            "workflow_audit": workflow_audit_server.server,
        }

    async def list_tools(self, server_key: str) -> list[ToolSpec]:
        tools = await self._servers[server_key].list_tools()
        return [
            ToolSpec(server_key=server_key, name=t.name, description=t.description or "", input_schema=t.input_schema)
            for t in tools
        ]

    async def call(self, server_key: str, tool_name: str, arguments: dict) -> Any:
        try:
            result = await self._servers[server_key].call_tool(tool_name, arguments)
        except Exception as exc:  # the in-process call path raises rather than returning is_error
            raise MCPToolError(str(exc)) from exc
        return _unwrap_call_result(result)


class StdioToolDispatcher:
    """Spawns each MCP server as a real subprocess and talks MCP over stdio."""

    def __init__(self):
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, Any] = {}

    async def __aenter__(self) -> "StdioToolDispatcher":
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
        for key, module in MCP_SERVER_MODULES.items():
            params = StdioServerParameters(command=sys.executable, args=["-m", module], env=env)
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[key] = session
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.__aexit__(*exc_info)

    async def list_tools(self, server_key: str) -> list[ToolSpec]:
        result = await self._sessions[server_key].list_tools()
        return [
            ToolSpec(server_key=server_key, name=t.name, description=t.description or "", input_schema=t.input_schema)
            for t in result.tools
        ]

    async def call(self, server_key: str, tool_name: str, arguments: dict) -> Any:
        result = await self._sessions[server_key].call_tool(tool_name, arguments)
        return _unwrap_call_result(result)


def _default_llm_call(model: str, system: str, messages: list[dict], tools: list[dict]):
    """Uses whatever Anthropic credentials are already configured in the
    environment (ANTHROPIC_API_KEY, or ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL) -
    the anthropic SDK resolves these itself; nothing is set explicitly here.
    """
    import anthropic

    client = anthropic.Anthropic()
    return client.messages.create(model=model, max_tokens=4096, system=system, messages=messages, tools=tools)


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    raise ValueError(f"could not extract a JSON object from agent output: {text!r}")


class ToolCallingAgent:
    """A minimal Anthropic tool-use loop: calls MCP tools until the model
    stops requesting them, then parses the final message as JSON."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tool_specs: list[ToolSpec],
        dispatcher: ToolDispatcher,
        case_id: str,
        model: str = ANTHROPIC_MODEL,
        max_turns: int = 6,
        llm_call: Callable | None = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tool_specs = tool_specs
        self.dispatcher = dispatcher
        self.case_id = case_id
        self.model = model
        self.max_turns = max_turns
        self.llm_call = llm_call or _default_llm_call

    async def run(self, user_prompt: str) -> dict:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in self.tool_specs
        ]
        tool_map = {t.name: t for t in self.tool_specs}
        messages: list[dict] = [{"role": "user", "content": user_prompt}]

        for _ in range(self.max_turns):
            response = await asyncio.to_thread(self.llm_call, self.model, self.system_prompt, messages, anthropic_tools)
            content_blocks = response.content
            messages.append({"role": "assistant", "content": content_blocks})

            tool_uses = [b for b in content_blocks if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                text = "".join(getattr(b, "text", "") for b in content_blocks if getattr(b, "type", None) == "text")
                return _extract_json(text)

            tool_result_blocks = []
            for tu in tool_uses:
                spec = tool_map.get(tu.name)
                if spec is None:
                    tool_result_blocks.append(
                        {"type": "tool_result", "tool_use_id": tu.id, "content": f"unknown tool {tu.name!r}", "is_error": True}
                    )
                    continue

                args = dict(tu.input)
                if "case_id" in spec.input_schema.get("properties", {}):
                    args["case_id"] = self.case_id

                try:
                    result = await self.dispatcher.call(spec.server_key, spec.name, args)
                    tool_result_blocks.append(
                        {"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result, default=str)}
                    )
                except MCPToolError as exc:
                    tool_result_blocks.append(
                        {"type": "tool_result", "tool_use_id": tu.id, "content": str(exc), "is_error": True}
                    )

            messages.append({"role": "user", "content": tool_result_blocks})

        raise RuntimeError(f"{self.name} exceeded max_turns={self.max_turns} without a final answer")


async def tools_for(dispatcher: ToolDispatcher, server_key: str, names: list[str]) -> list[ToolSpec]:
    """Fetch live tool schemas from a server and filter to the subset a
    given agent is allowed to see (least privilege, enforced at agent
    construction time)."""
    all_tools = await dispatcher.list_tools(server_key)
    by_name = {t.name: t for t in all_tools}
    missing = set(names) - set(by_name)
    if missing:
        raise ValueError(f"server {server_key!r} has no tools named {missing}")
    return [by_name[n] for n in names]
