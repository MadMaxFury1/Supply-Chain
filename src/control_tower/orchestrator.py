"""Deterministic orchestrator.

Sequences the Demand, Inventory, Supply, and Manufacturing investigation
agents against a case, builds the candidate mitigation options the
Decision agent may choose among, hands off to the Decision agent, and
narrates progress to the audit trail.

This module is explicitly NOT an LLM agent - per CLAUDE.md's Do-Not rule
("don't create an agent where a deterministic service is sufficient") and
Principle 3 (deterministic logic stays outside the LLM), it is plain control
flow. Like risk_detector.py and guardrails/policy.py, it accesses the
control tower's own case/audit tables directly rather than through MCP;
enterprise data (demand, inventory, supplier, approvals) is only ever
touched by the LLM agents, and only through MCP tools.
"""
from __future__ import annotations

import json
from typing import Callable

from sqlalchemy import select

from control_tower.agents.base import ToolDispatcher
from control_tower.agents.decision_agent import run_decision_agent
from control_tower.agents.demand_agent import run_demand_agent
from control_tower.agents.inventory_agent import run_inventory_agent
from control_tower.agents.manufacturing_agent import run_manufacturing_agent
from control_tower.agents.supply_agent import run_supply_agent
from control_tower.audit.trail import record_event
from control_tower.config import DEFAULT_LEAD_TIME_DAYS, DEFAULT_SAFETY_BUFFER_DAYS
from control_tower.db.models import Case, InventoryPosition, PurchaseOrder, Supplier
from control_tower.db.session import get_session
from control_tower.domain.risk_detector import _avg_daily_demand

ACTOR = "orchestrator"

NO_SUPPLIER_FINDING = {
    "cause_category": "no_supplier_on_record",
    "evidence": "No open purchase order exists for this product, so no supplier could be identified to investigate.",
    "confidence": 0.0,
    "contributes": False,
}


def _resolve_supplier_id(product_id: str) -> str | None:
    """Find the supplier on the case's most time-critical open PO -
    deterministic lookup, not the Supply agent's job to discover."""
    with get_session() as session:
        po = (
            session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.product_id == product_id, PurchaseOrder.status.in_(("OPEN", "DELAYED")))
                .order_by(PurchaseOrder.expected_date.asc())
            )
            .scalars()
            .first()
        )
        return po.supplier_id if po else None


def _candidate_options(product_id: str, site_id: str) -> list[dict]:
    """Deterministically build the set of mitigation options the Decision
    agent may choose among, based on what actually exists for this case:
    an open PO to expedite, and/or a healthier alternate supplier for an
    emergency PO sized to cover the demand/safety-stock gap."""
    options: list[dict] = []
    with get_session() as session:
        po = (
            session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.product_id == product_id, PurchaseOrder.status.in_(("OPEN", "DELAYED")))
                .order_by(PurchaseOrder.expected_date.asc())
            )
            .scalars()
            .first()
        )
        if po is not None:
            options.append({"action_type": "expedite_shipment", "params": {"po_id": po.po_id}})

        position = (
            session.execute(
                select(InventoryPosition)
                .where(InventoryPosition.product_id == product_id, InventoryPosition.site_id == site_id)
                .order_by(InventoryPosition.as_of_date.desc())
            )
            .scalars()
            .first()
        )
        on_hand = position.on_hand_qty if position else 0.0
        avg_demand = _avg_daily_demand(session, product_id, site_id)
        target_qty = avg_demand * (DEFAULT_LEAD_TIME_DAYS + DEFAULT_SAFETY_BUFFER_DAYS)
        qty = max(round(target_qty - on_hand), 1)

        current_supplier_id = po.supplier_id if po else None
        alt_supplier = (
            session.execute(
                select(Supplier)
                .where(Supplier.supplier_id != current_supplier_id)
                .order_by(Supplier.reliability_score.desc())
            )
            .scalars()
            .first()
        )
        if alt_supplier is not None:
            options.append({"action_type": "emergency_po", "params": {"supplier_id": alt_supplier.supplier_id, "qty": qty}})

    return options


async def run_orchestration(dispatcher: ToolDispatcher, case_id: str, llm_call: Callable | None = None) -> dict:
    """Runs the full investigation -> decision sequence for an OPEN case.
    Leaves the case in PENDING_APPROVAL (or unchanged, if the Decision agent's
    recommendation was denied by Gate A) - execution only happens after a
    human resolves the resulting approval."""
    with get_session() as session:
        case = session.get(Case, case_id)
        if case is None:
            raise ValueError(f"unknown case_id {case_id!r}")
        product_id, site_id = case.product_id, case.site_id
        case.status = "INVESTIGATING"
        record_event(session, case_id, ACTOR, "investigation_started",
                     {"product_id": product_id, "site_id": site_id}, "SUCCESS")

    supplier_id = _resolve_supplier_id(product_id)

    demand_finding = await run_demand_agent(dispatcher, case_id, product_id, site_id, llm_call=llm_call)
    inventory_finding = await run_inventory_agent(dispatcher, case_id, product_id, site_id, llm_call=llm_call)
    supply_finding = (
        await run_supply_agent(dispatcher, case_id, product_id, supplier_id, llm_call=llm_call)
        if supplier_id
        else dict(NO_SUPPLIER_FINDING)
    )
    manufacturing_finding = await run_manufacturing_agent(dispatcher, case_id, product_id, llm_call=llm_call)
    findings = {
        "demand": demand_finding,
        "inventory": inventory_finding,
        "supply": supply_finding,
        "manufacturing": manufacturing_finding,
    }

    candidate_options = _candidate_options(product_id, site_id)

    with get_session() as session:
        case = session.get(Case, case_id)
        case.findings_json = json.dumps(findings, default=str)
        record_event(session, case_id, ACTOR, "investigation_completed", {"findings": findings}, "SUCCESS")

    decision = await run_decision_agent(
        dispatcher, case_id, product_id, site_id,
        findings=list(findings.values()), candidate_options=candidate_options, llm_call=llm_call,
    )

    with get_session() as session:
        record_event(session, case_id, ACTOR, "decision_recorded", {"decision": decision}, "SUCCESS")

    return {"case_id": case_id, "findings": findings, "candidate_options": candidate_options, "decision": decision}
