"""Demand Investigation Agent - LLM-backed, tool-calling.

Investigates whether a demand-side cause (spike, forecast error) is
contributing to a stockout risk case. Reasons over MCP data only; never
touches the database directly (CLAUDE.md Principle 1).
"""
from __future__ import annotations

from typing import Callable

from control_tower.agents.base import ToolCallingAgent, ToolDispatcher, tools_for
from control_tower.skills import investigation_finding_contract

SYSTEM_PROMPT = """You are the Demand Investigation Agent in a pharmaceutical \
supply chain control tower. You investigate whether demand-side factors are \
contributing to a stockout risk case for a specific product and site.

You have a `get_demand_forecast` tool. Call it to compare recent actual \
demand against forecast over the last several months. Look for demand \
spikes, sustained forecast error, or trend shifts.

""" + investigation_finding_contract("demand-side factors")

TOOLS = ["get_demand_forecast"]


async def run_demand_agent(
    dispatcher: ToolDispatcher,
    case_id: str,
    product_id: str,
    site_id: str,
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = await tools_for(dispatcher, "inventory", TOOLS)
    agent = ToolCallingAgent(
        name="demand_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        llm_call=llm_call,
    )
    prompt = f"Investigate demand-side causes for case {case_id}: product_id={product_id}, site_id={site_id}."
    return await agent.run(prompt)
