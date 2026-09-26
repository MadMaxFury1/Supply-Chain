"""Execution Agent - LLM-backed, tool-calling.

Runs once a human has resolved an approval as APPROVED. Guardrail Gate B
lives *inside* the write tools themselves (see guardrails/policy.py) - this
agent cannot execute anything that wasn't actually approved, and a second
call for the same approval is denied there too (idempotency), not by this
agent's own discipline.

Executes the one approved action, verifies the resulting state with a read
tool, and closes the case with a verification record.
"""
from __future__ import annotations

import json
from typing import Callable

from control_tower.agents.base import ToolCallingAgent, ToolDispatcher, tools_for

SYSTEM_PROMPT = """You are the Execution Agent in a pharmaceutical supply \
chain control tower. A human has approved exactly one mitigation action for \
a stockout risk case. Your job:

1. Execute the approved action by calling the matching write tool \
   (`create_expedite_shipment` for action_type "expedite_shipment", or \
   `create_emergency_po` for action_type "emergency_po") with the given \
   approval_id and the approved params.
2. Verify the result using a read tool (`get_inventory_position`, \
   `get_open_purchase_orders`, or `get_manufacturing_status` as appropriate) \
   to confirm the mitigation actually changed the state you expect.
3. Call `close_case` with a verification payload summarizing what you \
   confirmed.

If execution is denied, do not retry with different arguments and do not \
call close_case - report the denial in your final answer.

Once you are done, respond with ONLY a JSON object (no prose, no markdown \
fences):
{"executed": <true|false>, "execution_detail": "...", "verified": <true|false>, \
"verification_detail": "...", "case_closed": <true|false>}"""

TOOLS = {
    "supplier": ["create_expedite_shipment", "create_emergency_po"],
    "inventory": ["get_inventory_position", "get_open_purchase_orders"],
    "workflow_audit": ["close_case"],
}


async def run_execution_agent(
    dispatcher: ToolDispatcher,
    case_id: str,
    approval_id: str,
    action_type: str,
    params: dict,
    product_id: str,
    site_id: str,
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = []
    for server_key, names in TOOLS.items():
        tool_specs.extend(await tools_for(dispatcher, server_key, names))

    agent = ToolCallingAgent(
        name="execution_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        llm_call=llm_call,
    )
    prompt = (
        f"Case {case_id}: product_id={product_id}, site_id={site_id}.\n"
        f"Approved action: approval_id={approval_id}, action_type={action_type!r}, params={json.dumps(params)}."
    )
    return await agent.run(prompt)
