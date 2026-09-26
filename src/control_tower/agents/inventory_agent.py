"""Inventory Investigation Agent - LLM-backed, tool-calling.

Investigates whether inventory-position factors (thin on-hand stock
relative to safety stock, no cushion from open POs) are contributing to a
stockout risk case.
"""
from __future__ import annotations

from typing import Callable

from control_tower.agents.base import MCPToolError, ToolCallingAgent, ToolDispatcher, tools_for
from control_tower.agents.reallocation_scout_agent import run_reallocation_scout
from control_tower.skills import investigation_finding_contract

SYSTEM_PROMPT = """You are the Inventory Investigation Agent in a pharmaceutical \
supply chain control tower. You investigate whether inventory-position factors \
are contributing to a stockout risk case for a specific product and site.

You have `get_inventory_position` and `get_open_purchase_orders` tools. Use \
them to check current on-hand quantity versus safety stock, and whether any \
open purchase orders would replenish stock in time.

""" + investigation_finding_contract("inventory-position factors")

TOOLS = ["get_inventory_position", "get_open_purchase_orders"]


async def run_inventory_agent(
    dispatcher: ToolDispatcher,
    case_id: str,
    product_id: str,
    site_id: str,
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = await tools_for(dispatcher, "inventory", TOOLS)
    agent = ToolCallingAgent(
        name="inventory_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        llm_call=llm_call,
    )
    prompt = f"Investigate inventory-position causes for case {case_id}: product_id={product_id}, site_id={site_id}."
    finding = await agent.run(prompt)

    if finding.get("cause_category") == "thin_safety_stock" and finding.get("contributes"):
        # Deterministic trigger - the parent's own code decides whether to consult its
        # sub-agent, not the model. A scout failure must never break or block the
        # primary finding, so it degrades gracefully rather than propagating.
        try:
            finding["reallocation_signal"] = await run_reallocation_scout(
                dispatcher, case_id, product_id, site_id, llm_call=llm_call
            )
        except (MCPToolError, RuntimeError):
            pass

    return finding
