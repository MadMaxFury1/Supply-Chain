from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from control_tower.db.models import Case, PurchaseOrder, utcnow
from control_tower.mcp_servers.workflow_audit_server import (
    close_case,
    create_approval_request,
    get_approval_status,
    get_audit_trail,
    resolve_approval,
    write_audit_event,
)

TODAY = date(2026, 9, 26)


def _open_case(db, case_id="CASE-1", status="INVESTIGATING"):
    case = Case(case_id=case_id, product_id="P1", site_id="S1", status=status,
                risk_score=2.5, days_of_supply=4.0, detected_at=utcnow())
    db.add(case)
    # the "expedite_shipment" scenarios used throughout this file reference PO-1
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY))
    db.commit()
    return case


def test_create_approval_request_success(db):
    _open_case(db)

    approval = create_approval_request(
        case_id="CASE-1", action_type="expedite_shipment", params={"po_id": "PO-1"}, summary="test",
    )

    assert approval.status == "PENDING"
    assert approval.action_type == "expedite_shipment"
    db.refresh(db.get(Case, "CASE-1"))
    assert db.get(Case, "CASE-1").status == "PENDING_APPROVAL"


def test_create_approval_request_denied_bad_action_type(db):
    _open_case(db)

    with pytest.raises(ToolError):
        create_approval_request(case_id="CASE-1", action_type="not_a_real_action", params={}, summary="x")

    # denial must not leave the case in PENDING_APPROVAL
    assert db.get(Case, "CASE-1").status == "INVESTIGATING"


def test_create_approval_request_denied_stock_reallocation(db):
    """`stock_reallocation` is deliberately excluded from ALLOWED_MITIGATION_ACTIONS
    (see config.py) - Gate A must deny it by name, not just as one of many bad
    strings. This is what keeps the Reallocation Scout sub-agent's advisory
    surplus-elsewhere signal (inventory_agent.py) from ever being escalated into
    an approvable/executable action."""
    _open_case(db)

    with pytest.raises(ToolError):
        create_approval_request(
            case_id="CASE-1", action_type="stock_reallocation",
            params={"from_site_id": "S2", "to_site_id": "S1", "qty": 100}, summary="x",
        )

    assert db.get(Case, "CASE-1").status == "INVESTIGATING"


def test_create_approval_request_denied_duplicate_in_flight(db):
    _open_case(db, status="PENDING_APPROVAL")

    with pytest.raises(ToolError):
        create_approval_request(case_id="CASE-1", action_type="expedite_shipment", params={"po_id": "PO-1"}, summary="x")


def test_resolve_approval_approved_transitions_case(db):
    _open_case(db)
    approval = create_approval_request(
        case_id="CASE-1", action_type="expedite_shipment", params={"po_id": "PO-1"}, summary="test",
    )

    resolved = resolve_approval(approval.approval_id, "APPROVED", decided_by="alice")

    assert resolved.status == "APPROVED"
    assert db.get(Case, "CASE-1").status == "APPROVED"


def test_resolve_approval_is_not_re_decidable(db):
    _open_case(db)
    approval = create_approval_request(
        case_id="CASE-1", action_type="expedite_shipment", params={"po_id": "PO-1"}, summary="test",
    )
    resolve_approval(approval.approval_id, "APPROVED", decided_by="alice")

    with pytest.raises(ToolError):
        resolve_approval(approval.approval_id, "REJECTED", decided_by="bob")

    # still APPROVED, second call had no effect
    assert get_approval_status(approval.approval_id).status == "APPROVED"


def test_close_case_requires_executing_status(db):
    _open_case(db, status="APPROVED")

    with pytest.raises(ToolError):
        close_case("CASE-1", verification={"ok": True})


def test_close_case_success(db):
    _open_case(db, status="EXECUTING")

    result = close_case("CASE-1", verification={"ok": True})

    assert result.status == "CLOSED"
    assert result.closed_at is not None


def test_audit_trail_captures_full_lifecycle(db):
    _open_case(db)
    write_audit_event(case_id="CASE-1", actor="orchestrator", action="case_opened", payload={}, outcome="SUCCESS")
    approval = create_approval_request(
        case_id="CASE-1", action_type="expedite_shipment", params={"po_id": "PO-1"}, summary="test",
    )
    resolve_approval(approval.approval_id, "APPROVED", decided_by="alice")

    trail = get_audit_trail("CASE-1")

    actions = [e.action for e in trail]
    assert actions == ["case_opened", "create_approval_request", "resolve_approval"]
