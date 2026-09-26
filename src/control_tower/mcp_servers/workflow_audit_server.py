"""Workflow & Audit MCP - the approval queue and the audit log. This is
the human-in-the-loop boundary (create_approval_request / resolve_approval)
and the single sink every case's audit trail is read from.

create_approval_request enforces Guardrail Gate A *inside the handler*
before writing anything - the Decision Agent recommends, this tool is what
actually decides whether a human even gets asked.

Run standalone: python -m control_tower.mcp_servers.workflow_audit_server
"""
from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from control_tower.audit.trail import get_trail, record_event
from control_tower.db.models import Approval, Case, utcnow
from control_tower.db.session import get_session
from control_tower.guardrails.policy import gate_a_pre_approval
from control_tower.hooks import on_case_closed

ACTOR = "workflow_audit_mcp"

server = MCPServer(
    name="workflow-audit-mcp",
    version="0.1.0",
    instructions=(
        "The approval queue (create_approval_request, get_approval_status, "
        "resolve_approval), case closure (close_case), and the audit trail "
        "(write_audit_event, get_audit_trail)."
    ),
)


class ApprovalOut(BaseModel):
    approval_id: str
    case_id: str
    action_type: str
    params: dict
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None


class AuditEventOut(BaseModel):
    event_id: int
    case_id: str | None
    actor: str
    action: str
    payload: dict
    outcome: str
    timestamp: str


class CaseOut(BaseModel):
    case_id: str
    product_id: str
    site_id: str
    status: str
    risk_score: float
    days_of_supply: float
    closed_at: str | None = None


def _approval_out(a: Approval) -> ApprovalOut:
    action = json.loads(a.recommended_action_json)
    return ApprovalOut(
        approval_id=a.approval_id, case_id=a.case_id, action_type=action["action_type"],
        params=action["params"], status=a.status, requested_at=a.requested_at.isoformat(),
        decided_at=a.decided_at.isoformat() if a.decided_at else None,
        decided_by=a.decided_by, decision_note=a.decision_note,
    )


@server.tool()
def create_approval_request(
    case_id: str, action_type: str, params: dict, summary: str, scenarios: list[dict] | None = None
) -> ApprovalOut:
    """Request human approval for a recommended mitigation. Runs Guardrail
    Gate A first and fails closed (raises ToolError, writes nothing) if the
    action isn't authorized for this case."""
    with get_session() as session:
        gate = gate_a_pre_approval(session, case_id, action_type, params)
        if not gate.allowed:
            record_event(
                session, case_id, ACTOR, "create_approval_request",
                {"action_type": action_type, "params": params, "reason": gate.reason}, "DENIED",
            )
            raise ToolError(f"guardrail Gate A denied approval request: {gate.reason}")

        approval = Approval(
            approval_id=f"APR-{uuid4().hex[:8].upper()}",
            case_id=case_id,
            recommended_action_json=json.dumps({"action_type": action_type, "params": params}),
            status="PENDING",
            requested_at=utcnow(),
        )
        session.add(approval)

        case = session.get(Case, case_id)
        case.status = "PENDING_APPROVAL"
        case.recommended_action_json = approval.recommended_action_json
        if scenarios:
            case.scenarios_json = json.dumps(scenarios, default=str)

        record_event(
            session, case_id, ACTOR, "create_approval_request",
            {"approval_id": approval.approval_id, "action_type": action_type, "params": params, "summary": summary},
            "SUCCESS",
        )
        return _approval_out(approval)


@server.tool()
def get_approval_status(approval_id: str) -> ApprovalOut:
    """Look up an approval request by id."""
    with get_session() as session:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise ToolError(f"unknown approval_id {approval_id!r}")
        return _approval_out(approval)


@server.tool()
def resolve_approval(
    approval_id: str, decision: Literal["APPROVED", "REJECTED"], decided_by: str, note: str = ""
) -> ApprovalOut:
    """Record a human decision on a pending approval. Idempotent: deciding
    an already-decided approval raises ToolError rather than re-deciding it,
    which is what prevents a repeated `approve` call from re-triggering
    execution."""
    with get_session() as session:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise ToolError(f"unknown approval_id {approval_id!r}")

        if approval.status != "PENDING":
            record_event(
                session, approval.case_id, ACTOR, "resolve_approval",
                {"approval_id": approval_id, "attempted_decision": decision}, "DENIED",
            )
            raise ToolError(f"approval {approval_id} already decided (status={approval.status})")

        approval.status = decision
        approval.decided_at = utcnow()
        approval.decided_by = decided_by
        approval.decision_note = note

        case = session.get(Case, approval.case_id)
        case.status = decision  # APPROVED | REJECTED
        if decision == "REJECTED":
            case.closed_at = utcnow()

        record_event(
            session, approval.case_id, ACTOR, "resolve_approval",
            {"approval_id": approval_id, "decision": decision, "decided_by": decided_by, "note": note},
            "SUCCESS",
        )
        return _approval_out(approval)


@server.tool()
def close_case(case_id: str, verification: dict, actor: str = "execution_agent") -> CaseOut:
    """Close a case after its approved action has been executed and
    verified. Requires the case to be in EXECUTING state."""
    with get_session() as session:
        case = session.get(Case, case_id)
        if case is None:
            raise ToolError(f"unknown case_id {case_id!r}")
        if case.status != "EXECUTING":
            raise ToolError(f"case {case_id} is not EXECUTING (status={case.status}); cannot close")

        case.status = "CLOSED"
        case.closed_at = utcnow()
        on_case_closed(case.case_id, case.status)

        record_event(session, case_id, actor, "close_case", {"verification": verification}, "SUCCESS")
        return CaseOut(
            case_id=case.case_id, product_id=case.product_id, site_id=case.site_id, status=case.status,
            risk_score=case.risk_score, days_of_supply=case.days_of_supply,
            closed_at=case.closed_at.isoformat() if case.closed_at else None,
        )


@server.tool()
def write_audit_event(case_id: str | None, actor: str, action: str, payload: dict, outcome: str = "SUCCESS") -> AuditEventOut:
    """Write a narrative audit event not tied to a specific domain tool call
    (e.g. 'orchestrator sequenced investigation', 'decision agent recommended X')."""
    with get_session() as session:
        event = record_event(session, case_id, actor, action, payload, outcome)
        return AuditEventOut(
            event_id=event.event_id, case_id=event.case_id, actor=event.actor, action=event.action,
            payload=payload, outcome=event.outcome, timestamp=event.timestamp.isoformat(),
        )


@server.tool()
def get_audit_trail(case_id: str) -> list[AuditEventOut]:
    """Return the full ordered audit trail for a case."""
    with get_session() as session:
        return [AuditEventOut(**e) for e in get_trail(session, case_id)]


if __name__ == "__main__":
    import asyncio

    asyncio.run(server.run_stdio_async())
