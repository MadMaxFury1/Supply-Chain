"""Manufacturing Investigation Agent - LLM-backed, tool-calling.

Investigates whether delayed manufacturing orders are contributing to a
stockout risk case for a specific product. Reasons over MCP data only;
never touches the database directly (CLAUDE.md Principle 1).
"""
from __future__ import annotations

from typing import Callable

from control_tower.agents.base import ToolCallingAgent, ToolDispatcher, tools_for
from control_tower.skills import investigation_finding_contract

SYSTEM_PROMPT = """You are the Manufacturing Investigation Agent in a pharmaceutical \
supply chain control tower. You investigate whether delayed manufacturing \
orders are contributing to a stockout risk case for a specific product.

You have a `get_manufacturing_status` tool. Use it to check whether any \
manufacturing orders for this product are delayed and whether their \
planned completion dates put the product's supply at risk.

""" + investigation_finding_contract("manufacturing order delays")

TOOLS = ["get_manufacturing_status"]


async def run_manufacturing_agent(
    dispatcher: ToolDispatcher,
    case_id: str,
    product_id: str,
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = await tools_for(dispatcher, "manufacturing", TOOLS)
    agent = ToolCallingAgent(
        name="manufacturing_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        llm_call=llm_call,
    )
    prompt = f"Investigate manufacturing-order delays for case {case_id}: product_id={product_id}."
    return await agent.run(prompt)
