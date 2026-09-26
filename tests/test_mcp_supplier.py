import json
from datetime import date, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from control_tower.db.models import Approval, Case, PurchaseOrder, Shipment, Supplier, utcnow
from control_tower.mcp_servers.supplier_server import (
    create_emergency_po,
    create_expedite_shipment,
    get_supplier_status,
)

TODAY = date(2026, 9, 26)


def _approved_case_and_approval(db, action_type: str, params: dict, case_id="CASE-1", approval_id="APR-1"):
    db.add(Case(case_id=case_id, product_id="P1", site_id="S1", status="APPROVED",
                risk_score=2.0, days_of_supply=4.0, detected_at=utcnow()))
    db.add(Approval(
        approval_id=approval_id, case_id=case_id,
        recommended_action_json=json.dumps({"action_type": action_type, "params": params}),
        status="APPROVED", requested_at=utcnow(), decided_at=utcnow(), decided_by="alice",
    ))
    db.commit()


def test_get_supplier_status(db):
    db.add(Supplier(supplier_id="SUP-1", name="Acme", reliability_score=0.9, country="USA"))
    db.commit()

    result = get_supplier_status("SUP-1")

    assert result.name == "Acme"


def test_create_expedite_shipment_success(db):
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=30)))
    db.add(Shipment(shipment_id="SHP-1", reference_type="PO", reference_id="PO-1", carrier="DHL",
                     status="DELAYED", origin="DE", destination="US", eta=TODAY + timedelta(days=30)))
    _approved_case_and_approval(db, "expedite_shipment", {"po_id": "PO-1"})

    result = create_expedite_shipment(approval_id="APR-1", po_id="PO-1", case_id="CASE-1")

    assert result.status == "EXECUTED"
    po = db.get(PurchaseOrder, "PO-1")
    assert po.status == "EXPEDITED"
    assert db.get(Case, "CASE-1").status == "EXECUTING"


def test_create_expedite_shipment_denied_when_not_approved(db):
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=30)))
    db.add(Case(case_id="CASE-1", product_id="P1", site_id="S1", status="PENDING_APPROVAL",
                risk_score=2.0, days_of_supply=4.0, detected_at=utcnow()))
    db.add(Approval(
        approval_id="APR-1", case_id="CASE-1",
        recommended_action_json=json.dumps({"action_type": "expedite_shipment", "params": {"po_id": "PO-1"}}),
        status="PENDING", requested_at=utcnow(),
    ))
    db.commit()

    with pytest.raises(ToolError):
        create_expedite_shipment(approval_id="APR-1", po_id="PO-1", case_id="CASE-1")

    assert db.get(PurchaseOrder, "PO-1").status == "DELAYED"


def test_create_expedite_shipment_denied_on_double_execution(db):
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=30)))
    _approved_case_and_approval(db, "expedite_shipment", {"po_id": "PO-1"})

    create_expedite_shipment(approval_id="APR-1", po_id="PO-1", case_id="CASE-1")

    with pytest.raises(ToolError):
        create_expedite_shipment(approval_id="APR-1", po_id="PO-1", case_id="CASE-1")


def test_create_expedite_shipment_denied_on_param_mismatch(db):
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=30)))
    db.add(PurchaseOrder(po_id="PO-2", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=30)))
    _approved_case_and_approval(db, "expedite_shipment", {"po_id": "PO-1"})

    # approval was for PO-1, attempting to execute against PO-2 must be denied
    with pytest.raises(ToolError):
        create_expedite_shipment(approval_id="APR-1", po_id="PO-2", case_id="CASE-1")


def test_create_emergency_po_success(db):
    db.add(Supplier(supplier_id="SUP-2", name="Backup Supplier", reliability_score=0.95, country="USA"))
    _approved_case_and_approval(db, "emergency_po", {"supplier_id": "SUP-2", "qty": 500.0})

    result = create_emergency_po(approval_id="APR-1", supplier_id="SUP-2", qty=500.0, case_id="CASE-1")

    assert result.status == "EXECUTED"
    assert db.get(Case, "CASE-1").status == "EXECUTING"
