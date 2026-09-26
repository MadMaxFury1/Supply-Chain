"""Hooks must be deterministic, observable, fail safe (CLAUDE.md); skills
are shared prompt fragments agents are equipped with. Kept minimal."""
import logging

from control_tower.agents.demand_agent import SYSTEM_PROMPT as DEMAND_PROMPT
from control_tower.agents.inventory_agent import SYSTEM_PROMPT as INVENTORY_PROMPT
from control_tower.agents.supply_agent import SYSTEM_PROMPT as SUPPLY_PROMPT
from control_tower.hooks import on_case_closed, on_case_opened
from control_tower.skills import investigation_finding_contract


def test_on_case_opened_is_observable(caplog):
    with caplog.at_level(logging.WARNING, logger="control_tower.hooks"):
        on_case_opened("CASE-1", "PRD-0001", "SITE-DC-01", 1.5)
    assert "CASE-1" in caplog.text
    assert "PRD-0001" in caplog.text


def test_on_case_closed_is_observable(caplog):
    with caplog.at_level(logging.INFO, logger="control_tower.hooks"):
        on_case_closed("CASE-1", "CLOSED")
    assert "CASE-1" in caplog.text
    assert "CLOSED" in caplog.text


def test_hooks_fail_safe_never_raise():
    # A bad risk_score breaks the "%.2f" log formatting internally - the
    # hook must swallow that, not propagate it into the caller's pipeline.
    on_case_opened("CASE-1", "PRD-0001", "SITE-DC-01", "not-a-float")


def test_investigation_finding_contract_embeds_factor_description():
    text = investigation_finding_contract("demand-side factors")
    assert "demand-side factors" in text
    assert '"contributes"' in text


def test_investigation_agents_share_the_finding_contract_skill():
    for prompt in (DEMAND_PROMPT, INVENTORY_PROMPT, SUPPLY_PROMPT):
        assert '"cause_category"' in prompt
        assert '"contributes"' in prompt
