"""Shared reusable prompt fragments ("skills") agents are equipped with -
distinct from tools: a skill is text injected into a system prompt, not
something dispatched over MCP. Kept here so the three investigation
agents don't each duplicate the same output-contract wording.
"""
from __future__ import annotations


def investigation_finding_contract(factor_description: str) -> str:
    """The structured-finding JSON contract every investigation agent
    (Demand/Inventory/Supply) must follow."""
    return (
        'When you are done investigating, respond with ONLY a JSON object (no prose, '
        'no markdown fences) of the form:\n'
        '{"cause_category": "<short label>", "evidence": "<1-3 sentence summary of what you found>", '
        '"confidence": <float 0-1>, "contributes": <true|false>}\n'
        f'"contributes" is true only if {factor_description} are a meaningful contributor '
        'to the stockout risk.'
    )
