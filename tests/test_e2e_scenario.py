"""End-to-end scenario test: detection -> investigation -> decision ->
approval -> execution -> verification -> audit trail, on a case shaped
like the seeded synthetic stockout scenario (thin stock, demand spike,
delayed PO, unreliable supplier). Uses stubbed LLM responses so it runs
without real API calls, but every tool call, guardrail check, and DB
mutation is real.
"""
import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from control_tower.agents.base import InProcessToolDispatcher, MCPToolError
from control_tower.agents.execution_agent import run_execution_agent
from control_tower.db.models import (
    Case,
    DemandForecast,
    InventoryPosition,
    Product,
    PurchaseOrder,
    Site,
    Supplier,
)
from control_tower.db.session import get_session
from control_tower.domain.risk_detector import detect_stockout_risks
from control_tower.orchestrator import run_orchestration

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


def _seed_stockout_scenario(db):
    db.add(Product(product_id="PRD-0001", name="OncoStat 50mg", ndc_code="0001-0001-01",
                    dosage_form="Infusion Bag", therapeutic_area="Oncology", is_critical=True))
    db.add(Site(site_id="SITE-DC-01", name="DC One", site_type="DC", country="USA"))
    db.add(Supplier(supplier_id="SUP-03", name="Flaky Co", reliability_score=0.52, country="IN"))
    db.add(Supplier(supplier_id="SUP-01", name="Reliable Co", reliability_score=0.95, country="USA"))
    db.add(InventoryPosition(product_id="PRD-0001", site_id="SITE-DC-01", on_hand_qty=117.7,
                              safety_stock_qty=168.1, unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="PRD-0001", site_id="SITE-DC-01", period=date(2026, 8, 1),
                           forecast_qty=336.2, actual_qty=336.2))
    db.add(DemandForecast(product_id="PRD-0001", site_id="SITE-DC-01", period=date(2026, 9, 1),
                           forecast_qty=336.2, actual_qty=874.1))
    db.add(PurchaseOrder(po_id="PO-SEED-01", product_id="PRD-0001", supplier_id="SUP-03", qty=400,
                          status="DELAYED", promised_date=TODAY - timedelta(days=18),
                          expected_date=TODAY + timedelta(days=27)))
    db.commit()


def test_full_lifecycle_detect_to_close_with_idempotency(db):
    _seed_stockout_scenario(db)

    with get_session() as session:
        new_cases = detect_stockout_risks(session, today=TODAY)
        assert len(new_cases) == 1
        case_id = new_cases[0].case_id
    assert db.get(Case, case_id).status == "OPEN"

    demand_finding = {"cause_category": "demand_spike", "evidence": "2.6x spike vs forecast", "confidence": 0.9, "contributes": True}
    inventory_finding = {"cause_category": "thin_safety_stock", "evidence": "on-hand below safety stock", "confidence": 0.85, "contributes": True}
    scout_finding = {
        "available": False,
        "evidence": "No other sites have an inventory position on record for this product.",
        "candidate_sites": [],
        "confidence": 0.9,
    }
    supply_finding = {"cause_category": "unreliable_supplier", "evidence": "reliability 0.52, PO badly delayed", "confidence": 0.8, "contributes": True}
    manufacturing_finding = {"cause_category": "none", "evidence": "no manufacturing orders in flight", "confidence": 0.1, "contributes": False}
    scenario = {"action_type": "expedite_shipment", "params": {"po_id": "PO-SEED-01"}, "tradeoff": "fastest, no extra cost"}
    decision_payload = {
        "scenarios": [scenario],
        "recommended_action_type": "expedite_shipment",
        "recommended_params": {"po_id": "PO-SEED-01"},
        "approval_id": "PLACEHOLDER",
        "rationale": "Expediting the existing PO is fastest given how close it already is.",
    }

    investigation_llm_call = _scripted_llm_call([
        _tool_use_response("get_demand_forecast", {"product_id": "PRD-0001", "site_id": "SITE-DC-01", "months": 6}),
        _text_response(demand_finding),
        _tool_use_response("get_inventory_position", {"product_id": "PRD-0001", "site_id": "SITE-DC-01"}, "tu_1"),
        _tool_use_response("get_open_purchase_orders", {"product_id": "PRD-0001"}, "tu_2"),
        _text_response(inventory_finding),
        _tool_use_response("list_inventory_positions", {"product_id": "PRD-0001", "exclude_site_id": "SITE-DC-01"}, "tu_1"),
        _text_response(scout_finding),
        _tool_use_response("get_supplier_status", {"supplier_id": "SUP-03"}, "tu_1"),
        _text_response(supply_finding),
        _tool_use_response("get_manufacturing_status", {"product_id": "PRD-0001"}, "tu_1"),
        _text_response(manufacturing_finding),
        _tool_use_response("create_approval_request", {
            "action_type": "expedite_shipment", "params": {"po_id": "PO-SEED-01"},
            "summary": "Expedite PO-SEED-01.", "scenarios": [scenario],
        }),
        _text_response(decision_payload),
    ])

    dispatcher = InProcessToolDispatcher()
    result = asyncio.run(run_orchestration(dispatcher, case_id, llm_call=investigation_llm_call))
    approval_id = result["decision"]["approval_id"]
    assert db.get(Case, case_id).status == "PENDING_APPROVAL"

    # look up the real approval_id created by the tool (the stub above used a placeholder)
    with get_session() as session:
        from control_tower.db.models import Approval
        approval = session.query(Approval).filter_by(case_id=case_id, status="PENDING").one()
        approval_id = approval.approval_id

    resolved = asyncio.run(dispatcher.call(
        "workflow_audit", "resolve_approval",
        {"approval_id": approval_id, "decision": "APPROVED", "decided_by": "alice", "note": ""},
    ))
    assert resolved["status"] == "APPROVED"
    assert db.get(Case, case_id).status == "APPROVED"

    execution_llm_call = _scripted_llm_call([
        _tool_use_response("create_expedite_shipment", {"approval_id": approval_id, "po_id": "PO-SEED-01"}, "tu_1"),
        _tool_use_response("get_open_purchase_orders", {"product_id": "PRD-0001"}, "tu_2"),
        _tool_use_response("close_case", {"verification": {"po_status": "EXPEDITED"}}, "tu_3"),
        _text_response({
            "executed": True, "execution_detail": "PO-SEED-01 expedited.",
            "verified": True, "verification_detail": "PO-SEED-01 status is now EXPEDITED.",
            "case_closed": True,
        }),
    ])
    exec_result = asyncio.run(run_execution_agent(
        dispatcher, case_id, approval_id, "expedite_shipment", {"po_id": "PO-SEED-01"},
        "PRD-0001", "SITE-DC-01", llm_call=execution_llm_call,
    ))

    assert exec_result["executed"] is True
    assert exec_result["case_closed"] is True
    case = db.get(Case, case_id)
    assert case.status == "CLOSED"
    assert case.closed_at is not None
    po = db.get(PurchaseOrder, "PO-SEED-01")
    assert po.status == "EXPEDITED"

    trail = asyncio.run(dispatcher.call("workflow_audit", "get_audit_trail", {"case_id": case_id}))
    actions = [e["action"] for e in trail]
    assert actions[0] == "investigation_started"
    assert "get_demand_forecast" in actions
    assert "get_inventory_position" in actions
    assert "get_supplier_status" in actions
    assert "investigation_completed" in actions
    assert "create_approval_request" in actions
    assert "decision_recorded" in actions
    assert "resolve_approval" in actions
    assert "create_expedite_shipment" in actions
    assert "close_case" in actions
    assert actions.index("investigation_started") < actions.index("create_approval_request")
    assert actions.index("create_approval_request") < actions.index("resolve_approval")
    assert actions.index("resolve_approval") < actions.index("create_expedite_shipment")
    assert actions.index("create_expedite_shipment") < actions.index("close_case")

    # idempotency: re-resolving or re-executing must be denied, not double-applied
    with pytest.raises(MCPToolError):
        asyncio.run(dispatcher.call(
            "workflow_audit", "resolve_approval",
            {"approval_id": approval_id, "decision": "APPROVED", "decided_by": "alice", "note": ""},
        ))
    with pytest.raises(MCPToolError):
        asyncio.run(dispatcher.call(
            "supplier", "create_expedite_shipment", {"approval_id": approval_id, "po_id": "PO-SEED-01", "case_id": case_id},
        ))

    assert db.get(Case, case_id).status == "CLOSED"
    assert db.get(PurchaseOrder, "PO-SEED-01").status == "EXPEDITED"
