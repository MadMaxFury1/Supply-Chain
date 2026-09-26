"""Supply Investigation Agent - LLM-backed, tool-calling.

Investigates whether low supplier reliability is contributing to a
stockout risk case. `supplier_id` is resolved by the (deterministic)
orchestrator from the case's open purchase orders and passed in -
discovering it isn't this agent's job.

Manufacturing-order delays are investigated separately by the
Manufacturing Agent (agents/manufacturing_agent.py) - this agent used to
cover both, but that duplicated responsibility once a dedicated
Manufacturing Agent was introduced (Phase 2), so this agent's scope was
narrowed to supplier reliability only. See
docs/architecture/phase2-manufacturing-agent.md.
"""
from __future__ import annotations

from typing import Callable

from control_tower.agents.base import ToolCallingAgent, ToolDispatcher, tools_for
from control_tower.skills import investigation_finding_contract

SYSTEM_PROMPT = """You are the Supply Investigation Agent in a pharmaceutical \
supply chain control tower. You investigate whether low supplier reliability \
is contributing to a stockout risk case for a specific product.

You have a `get_supplier_status` tool. Use it to check the relevant \
supplier's reliability score.

""" + investigation_finding_contract("supplier reliability")

TOOLS = ["get_supplier_status"]


async def run_supply_agent(
    dispatcher: ToolDispatcher,
    case_id: str,
    product_id: str,
    supplier_id: str,
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = await tools_for(dispatcher, "supplier", TOOLS)
    agent = ToolCallingAgent(
        name="supply_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        llm_call=llm_call,
    )
    prompt = f"Investigate supplier/manufacturing causes for case {case_id}: product_id={product_id}, supplier_id={supplier_id}."
    return await agent.run(prompt)
