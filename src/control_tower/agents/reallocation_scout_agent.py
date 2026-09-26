"""Reallocation Scout - LLM-backed, tool-calling sub-agent of the Inventory
Agent.

Read-only and advisory only: it checks whether other sites hold surplus
on-hand stock of the same product that could plausibly cover a deficit site's
shortfall. It never recommends or triggers an actual transfer - no MCP write
tool for that exists (`stock_reallocation` is deliberately excluded from
`ALLOWED_MITIGATION_ACTIONS`, see config.py), so its output can only ever
enrich a finding as extra evidence, never become an executable action.

Invoked deterministically by `inventory_agent.py` (the parent decides
whether to call it, not the model) when the Inventory Agent's own finding is
a contributing thin-safety-stock case.
"""
from __future__ import annotations

from typing import Callable

from control_tower.agents.base import ToolCallingAgent, ToolDispatcher, tools_for

SYSTEM_PROMPT = """You are the Reallocation Scout, a read-only advisory sub-agent of the \
Inventory Investigation Agent in a pharmaceutical supply chain control tower. Your only job \
is to check whether other sites hold surplus on-hand stock of a product that a deficit site \
is short on, as an extra signal for a human decision-maker.

You have `list_inventory_positions` to see every other site's current position for the \
product. A site has surplus if its on-hand quantity is meaningfully above its own safety \
stock target.

You are strictly advisory: you never claim stock has been or will be transferred, and you \
never recommend or imply an action to execute - no such action exists in this system. You \
only report whether a surplus signal exists elsewhere.

When you are done, respond with ONLY a JSON object (no prose, no markdown fences) of the form:
{"available": <true|false>, "evidence": "<1-3 sentence summary of what you found>", \
"candidate_sites": [<site_id strings with surplus>], "confidence": <float 0-1>}
"""

TOOLS = ["list_inventory_positions"]


async def run_reallocation_scout(
    dispatcher: ToolDispatcher,
    case_id: str,
    product_id: str,
    deficit_site_id: str,
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = await tools_for(dispatcher, "inventory", TOOLS)
    agent = ToolCallingAgent(
        name="reallocation_scout_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        max_turns=3,
        llm_call=llm_call,
    )
    prompt = (
        f"Check for reallocation signal for case {case_id}: product_id={product_id}, "
        f"deficit_site_id={deficit_site_id}. Call list_inventory_positions with "
        f"exclude_site_id={deficit_site_id!r} to see the other sites."
    )
    return await agent.run(prompt)
