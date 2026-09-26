"""Agent-behavior tests for the Decision and Execution agents.

Stub the LLM with scripted tool-use then final-answer responses, exercising
the real ToolCallingAgent loop, real MCP tools, and real guardrails against
a test DB.
"""
import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

from control_tower.agents.base import InProcessToolDispatcher
from control_tower.agents.decision_agent import run_decision_agent
from control_tower.agents.execution_agent import run_execution_agent
from control_tower.db.models import Approval, Case, InventoryPosition, PurchaseOrder, utcnow

TODAY = date(2026, 9, 26)


def _text_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def _tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", id=tool_use_id, name=tool_name, input=tool_input)]
    )


def _scripted_llm_call(responses):
    calls = iter(responses)

    def llm_call(model, system, messages, tools):
        return next(calls)

    return llm_call


def test_decision_agent_creates_approval_request(db):
    db.add(Case(case_id="CASE-1", product_id="P1", site_id="S1", status="INVESTIGATING",
                risk_score=2.0, days_of_supply=4.0, detected_at=utcnow()))
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=20)))
    db.commit()

    findings = [{"cause_category": "thin_safety_stock", "evidence": "on-hand below safety stock",
                 "confidence": 0.8, "contributes": True}]
    candidates = [{"action_type": "expedite_shipment", "params": {"po_id": "PO-1"}}]
    scenario = {"action_type": "expedite_shipment", "params": {"po_id": "PO-1"}, "tradeoff": "fast, no extra cost"}

    llm_call = _scripted_llm_call([
        _tool_use_response("create_approval_request", {
            "action_type": "expedite_shipment",
            "params": {"po_id": "PO-1"},
            "summary": "Expedite delayed PO-1 to cover thin safety stock.",
            "scenarios": [scenario],
        }),
        _text_response({
            "scenarios": [scenario],
            "recommended_action_type": "expedite_shipment",
            "recommended_params": {"po_id": "PO-1"},
            "approval_id": "PLACEHOLDER",
            "rationale": "Only viable option among candidates.",
        }),
    ])

    result = asyncio.run(
        run_decision_agent(InProcessToolDispatcher(), "CASE-1", "P1", "S1", findings, candidates, llm_call=llm_call)
    )

    assert result["recommended_action_type"] == "expedite_shipment"
    approval = db.query(Approval).filter_by(case_id="CASE-1").one()
    assert approval.status == "PENDING"
    assert db.get(Case, "CASE-1").status == "PENDING_APPROVAL"


def test_decision_agent_reports_denial(db):
    db.add(Case(case_id="CASE-1", product_id="P1", site_id="S1", status="PENDING_APPROVAL",
                risk_score=2.0, days_of_supply=4.0, detected_at=utcnow()))
    db.commit()

    llm_call = _scripted_llm_call([
        _tool_use_response("create_approval_request", {
            "action_type": "expedite_shipment", "params": {"po_id": "PO-1"},
            "summary": "x", "scenarios": [],
        }),
        _text_response({
            "scenarios": [], "recommended_action_type": "expedite_shipment",
            "recommended_params": {"po_id": "PO-1"}, "approval_id": None,
            "rationale": "Denied: case already has an approval in flight.",
        }),
    ])

    result = asyncio.run(
        run_decision_agent(InProcessToolDispatcher(), "CASE-1", "P1", "S1", [], [], llm_call=llm_call)
    )

    assert result["approval_id"] is None
    assert db.get(Case, "CASE-1").status == "PENDING_APPROVAL"  # unchanged, denial didn't mutate state


def test_execution_agent_executes_verifies_and_closes(db):
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY, expected_date=TODAY + timedelta(days=30)))
    db.add(InventoryPosition(product_id="P1", site_id="S1", on_hand_qty=50, safety_stock_qty=150,
                              unit_of_measure="units", as_of_date=TODAY))
    db.add(Case(case_id="CASE-1", product_id="P1", site_id="S1", status="APPROVED",
                risk_score=2.0, days_of_supply=4.0, detected_at=utcnow()))
    db.add(Approval(
        approval_id="APR-1", case_id="CASE-1",
        recommended_action_json=json.dumps({"action_type": "expedite_shipment", "params": {"po_id": "PO-1"}}),
        status="APPROVED", requested_at=utcnow(), decided_at=utcnow(), decided_by="alice",
    ))
    db.commit()

    llm_call = _scripted_llm_call([
        _tool_use_response("create_expedite_shipment", {"approval_id": "APR-1", "po_id": "PO-1"}, "tu_1"),
        _tool_use_response("get_open_purchase_orders", {"product_id": "P1"}, "tu_2"),
        _tool_use_response("close_case", {"verification": {"po_status": "EXPEDITED"}}, "tu_3"),
        _text_response({
            "executed": True, "execution_detail": "PO-1 expedited.",
            "verified": True, "verification_detail": "PO-1 status is EXPEDITED.",
            "case_closed": True,
        }),
    ])

    result = asyncio.run(run_execution_agent(
        InProcessToolDispatcher(), "CASE-1", "APR-1", "expedite_shipment", {"po_id": "PO-1"}, "P1", "S1",
        llm_call=llm_call,
    ))

    assert result["executed"] is True
    assert result["case_closed"] is True
    assert db.get(Case, "CASE-1").status == "CLOSED"
    assert db.get(PurchaseOrder, "PO-1").status == "EXPEDITED"


def test_execution_agent_denied_execution_does_not_close_case(db):
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

    llm_call = _scripted_llm_call([
        _tool_use_response("create_expedite_shipment", {"approval_id": "APR-1", "po_id": "PO-1"}, "tu_1"),
        _text_response({
            "executed": False, "execution_detail": "Gate B denied: approval is not APPROVED.",
            "verified": False, "verification_detail": "", "case_closed": False,
        }),
    ])

    result = asyncio.run(run_execution_agent(
        InProcessToolDispatcher(), "CASE-1", "APR-1", "expedite_shipment", {"po_id": "PO-1"}, "P1", "S1",
        llm_call=llm_call,
    ))

    assert result["executed"] is False
    assert db.get(Case, "CASE-1").status == "PENDING_APPROVAL"
    assert db.get(PurchaseOrder, "PO-1").status == "DELAYED"
