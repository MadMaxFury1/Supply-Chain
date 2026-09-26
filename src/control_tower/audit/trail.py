"""Shared audit-writing helper.

Every MCP tool handler calls `record_event` itself as part of its own
transaction, so an audit trail exists regardless of whether the calling
agent remembers to log anything - the audit boundary is the tool, not
agent discipline. `workflow_audit_mcp`'s `write_audit_event` tool uses this
same function for higher-level narrative events (case opened, human
decision, etc.) that aren't tied to a single domain tool call.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from control_tower.db.models import AuditEvent, utcnow


def record_event(
    session: Session,
    case_id: str | None,
    actor: str,
    action: str,
    payload: dict,
    outcome: str,
) -> AuditEvent:
    event = AuditEvent(
        case_id=case_id,
        actor=actor,
        action=action,
        payload_json=json.dumps(payload, default=str),
        outcome=outcome,
        timestamp=utcnow(),
    )
    session.add(event)
    session.flush()
    return event


def get_trail(session: Session, case_id: str) -> list[dict]:
    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.case_id == case_id)
        .order_by(AuditEvent.timestamp.asc(), AuditEvent.event_id.asc())
        .all()
    )
    return [
        {
            "event_id": e.event_id,
            "case_id": e.case_id,
            "actor": e.actor,
            "action": e.action,
            "payload": json.loads(e.payload_json),
            "outcome": e.outcome,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]
