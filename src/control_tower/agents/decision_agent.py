"""Decision Agent - LLM-backed, tool-calling.

Synthesizes the Demand/Inventory/Supply investigation findings into 2-3
ranked mitigation scenarios, picks a recommendation, and requests human
approval via `create_approval_request` on workflow_audit_mcp. Guardrail
Gate A runs *inside* that tool (see guardrails/policy.py) - this agent
cannot bypass it by reasoning around it, it can only get denied.
"""
from __future__ import annotations

import json
from typing import Callable

from control_tower.agents.base import ToolCallingAgent, ToolDispatcher, tools_for

SYSTEM_PROMPT = """You are the Decision Agent in a pharmaceutical supply chain \
control tower. You receive root-cause findings from the Demand, Inventory, \
Supply, and Manufacturing investigation agents for a stockout risk case, \
plus the candidate mitigation options actually available for it.

Your job:
1. Weigh the findings and propose 2-3 ranked mitigation scenarios, each with \
   a brief cost/lead-time/risk tradeoff, drawn ONLY from the candidate \
   options you were given - never invent an action or params not listed.
2. Pick the single best scenario as your recommendation.
3. Call the `create_approval_request` tool with that recommendation's \
   action_type and params, a one-sentence summary, and your full list of \
   scenarios (each as {"action_type", "params", "tradeoff"}).

This call only queues the action for human approval - it does not execute \
anything. If the tool call is denied, explain why in your final answer \
instead of retrying with a different action.

Once you have called the tool (successfully or not), respond with ONLY a \
JSON object (no prose, no markdown fences):
{"scenarios": [{"action_type": "...", "params": {...}, "tradeoff": "..."}, ...], \
"recommended_action_type": "...", "recommended_params": {...}, \
"approval_id": "<id from the tool result, or null if denied>", \
"rationale": "..."}"""

TOOLS = ["create_approval_request"]


async def run_decision_agent(
    dispatcher: ToolDispatcher,
    case_id: str,
    product_id: str,
    site_id: str,
    findings: list[dict],
    candidate_options: list[dict],
    llm_call: Callable | None = None,
) -> dict:
    tool_specs = await tools_for(dispatcher, "workflow_audit", TOOLS)
    agent = ToolCallingAgent(
        name="decision_agent",
        system_prompt=SYSTEM_PROMPT,
        tool_specs=tool_specs,
        dispatcher=dispatcher,
        case_id=case_id,
        llm_call=llm_call,
    )
    prompt = (
        f"Case {case_id}: product_id={product_id}, site_id={site_id}.\n\n"
        f"Investigation findings:\n{json.dumps(findings, indent=2)}\n\n"
        f"Candidate mitigation options (choose only among these):\n{json.dumps(candidate_options, indent=2)}"
    )
    return await agent.run(prompt)
