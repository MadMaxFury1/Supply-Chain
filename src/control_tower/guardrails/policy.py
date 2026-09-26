"""Deterministic guardrail policy - CLAUDE.md is explicit that security,
authorization and compliance must never rely solely on LLM instructions.

These functions are called *inside* the MCP tool handlers that create
approval requests and execute mitigations (not just from orchestration
code), so a check here is the actual runtime enforcement boundary, not a
suggestion an agent could route around. Every check fails closed: on any
doubt, `allowed=False`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from control_tower.config import ALLOWED_MITIGATION_ACTIONS, APPROVAL_EXPIRY_HOURS, MAX_EMERGENCY_PO_QTY
from control_tower.db.models import Approval, Case, PurchaseOrder, utcnow

NON_APPROVABLE_CASE_STATUSES = ("PENDING_APPROVAL", "APPROVED", "EXECUTING", "CLOSED")


@dataclass
class GuardrailResult:
    allowed: bool
    gate: str
    reason: str


def _deny(gate: str, reason: str) -> GuardrailResult:
    return GuardrailResult(allowed=False, gate=gate, reason=reason)


def _allow(gate: str) -> GuardrailResult:
    return GuardrailResult(allowed=True, gate=gate, reason="ok")


def gate_a_pre_approval(session: Session, case_id: str, action_type: str, params: dict) -> GuardrailResult:
    """Runs before an approval request may be created for a case."""
    case = session.get(Case, case_id)
    if case is None:
        return _deny("A", f"unknown case_id {case_id!r}")

    if case.status in NON_APPROVABLE_CASE_STATUSES:
        return _deny("A", f"case {case_id} already has an approval in flight (status={case.status})")

    if action_type not in ALLOWED_MITIGATION_ACTIONS:
        return _deny("A", f"action_type {action_type!r} is not an authorized mitigation action")

    if action_type == "emergency_po":
        qty = params.get("qty")
        if not isinstance(qty, (int, float)) or qty <= 0:
            return _deny("A", "emergency_po requires a positive qty")
        if qty > MAX_EMERGENCY_PO_QTY:
            return _deny("A", f"emergency_po qty {qty} exceeds policy max {MAX_EMERGENCY_PO_QTY}")
        if not params.get("supplier_id"):
            return _deny("A", "emergency_po requires supplier_id")

    elif action_type == "expedite_shipment":
        po_id = params.get("po_id")
        if not po_id:
            return _deny("A", "expedite_shipment requires po_id")
        po = session.get(PurchaseOrder, po_id)
        if po is None or po.product_id != case.product_id:
            return _deny("A", f"po_id {po_id!r} does not belong to case {case_id}'s product")

    return _allow("A")


def gate_b_pre_execution(session: Session, approval_id: str, action_type: str, params: dict) -> GuardrailResult:
    """Runs immediately before the write tool executes the mitigation.

    On success, atomically flips the case to EXECUTING so a second call
    (e.g. a retried or duplicated execution request) is denied rather than
    executing twice - the idempotency guarantee lives here, not in the
    caller's discipline.
    """
    approval = session.get(Approval, approval_id)
    if approval is None:
        return _deny("B", f"unknown approval_id {approval_id!r}")

    if approval.status != "APPROVED":
        return _deny("B", f"approval {approval_id} is not APPROVED (status={approval.status})")

    if utcnow() - approval.requested_at > timedelta(hours=APPROVAL_EXPIRY_HOURS):
        return _deny("B", f"approval {approval_id} expired (older than {APPROVAL_EXPIRY_HOURS}h)")

    import json

    approved_action = json.loads(approval.recommended_action_json)
    if approved_action.get("action_type") != action_type or approved_action.get("params") != params:
        return _deny("B", "requested execution does not match the approved action - possible tampering")

    case = session.get(Case, approval.case_id)
    if case is None:
        return _deny("B", f"approval {approval_id} references unknown case")
    if case.status != "APPROVED":
        return _deny("B", f"case {case.case_id} is not in APPROVED state (status={case.status}); "
                          f"already executed or executing")

    case.status = "EXECUTING"
    session.flush()
    return _allow("B")
