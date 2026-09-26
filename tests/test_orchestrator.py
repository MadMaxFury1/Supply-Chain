"""Integration test for the deterministic orchestrator: sequences all three
investigation agents and the decision agent against a seeded case, using a
single scripted LLM stub (each agent's turns are consumed off the same
queue in call order since they run sequentially, not concurrently)."""
import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

from control_tower.agents.base import InProcessToolDispatcher
from control_tower.db.models import (
    Approval,
    Case,
    DemandForecast,
    InventoryPosition,
    Product,
    PurchaseOrder,
    Site,
    Supplier,
    utcnow,
)
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


def _seed(db):
    db.add(Product(product_id="P1", name="OncoStat", ndc_code="0000-0000-00", dosage_form="Infusion Bag",
                    therapeutic_area="Oncology", is_critical=True))
    db.add(Site(site_id="S1", name="DC One", site_type="DC", country="USA"))
    db.add(Supplier(supplier_id="SUP-1", name="Flaky Co", reliability_score=0.4, country="IN"))
    db.add(Supplier(supplier_id="SUP-2", name="Reliable Co", reliability_score=0.95, country="USA"))
    db.add(InventoryPosition(product_id="P1", site_id="S1", on_hand_qty=50, safety_stock_qty=150,
                              unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="P1", site_id="S1", period=date(2026, 8, 1), forecast_qty=100, actual_qty=95))
    db.add(DemandForecast(product_id="P1", site_id="S1", period=date(2026, 9, 1), forecast_qty=100, actual_qty=260))
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY - timedelta(days=10), expected_date=TODAY + timedelta(days=20)))
    db.add(Case(case_id="CASE-1", product_id="P1", site_id="S1", status="OPEN",
                risk_score=2.0, days_of_supply=4.0, detected_at=utcnow()))
    db.commit()


def test_orchestration_runs_end_to_end_to_pending_approval(db):
    _seed(db)

    demand_finding = {"cause_category": "demand_spike", "evidence": "2.6x spike", "confidence": 0.9, "contributes": True}
    inventory_finding = {"cause_category": "thin_safety_stock", "evidence": "below target", "confidence": 0.85, "contributes": True}
    scout_finding = {
        "available": False,
        "evidence": "No other sites have an inventory position on record for this product.",
        "candidate_sites": [],
        "confidence": 0.9,
    }
    supply_finding = {"cause_category": "unreliable_supplier", "evidence": "reliability 0.4", "confidence": 0.7, "contributes": True}
    manufacturing_finding = {"cause_category": "none", "evidence": "no manufacturing orders in flight", "confidence": 0.1, "contributes": False}
    scenario = {"action_type": "expedite_shipment", "params": {"po_id": "PO-1"}, "tradeoff": "fastest, no extra cost"}
    decision_payload = {
        "scenarios": [scenario],
        "recommended_action_type": "expedite_shipment",
        "recommended_params": {"po_id": "PO-1"},
        "approval_id": "PLACEHOLDER",
        "rationale": "Expediting the existing delayed PO is the fastest fix.",
    }

    llm_call = _scripted_llm_call([
        # demand agent
        _tool_use_response("get_demand_forecast", {"product_id": "P1", "site_id": "S1", "months": 6}),
        _text_response(demand_finding),
        # inventory agent
        _tool_use_response("get_inventory_position", {"product_id": "P1", "site_id": "S1"}, "tu_1"),
        _tool_use_response("get_open_purchase_orders", {"product_id": "P1"}, "tu_2"),
        _text_response(inventory_finding),
        # reallocation scout (sub-agent of the inventory agent)
        _tool_use_response("list_inventory_positions", {"product_id": "P1", "exclude_site_id": "S1"}, "tu_1"),
        _text_response(scout_finding),
        # supply agent (supplier_id SUP-1 resolved from PO-1)
        _tool_use_response("get_supplier_status", {"supplier_id": "SUP-1"}, "tu_1"),
        _text_response(supply_finding),
        # manufacturing agent
        _tool_use_response("get_manufacturing_status", {"product_id": "P1"}, "tu_1"),
        _text_response(manufacturing_finding),
        # decision agent
        _tool_use_response("create_approval_request", {
            "action_type": "expedite_shipment", "params": {"po_id": "PO-1"},
            "summary": "Expedite PO-1.", "scenarios": [scenario],
        }),
        _text_response(decision_payload),
    ])

    result = asyncio.run(run_orchestration(InProcessToolDispatcher(), "CASE-1", llm_call=llm_call))

    assert result["findings"]["demand"] == demand_finding
    assert result["findings"]["inventory"]["reallocation_signal"] == scout_finding
    assert {k: v for k, v in result["findings"]["inventory"].items() if k != "reallocation_signal"} == inventory_finding
    assert result["findings"]["supply"] == supply_finding
    assert result["findings"]["manufacturing"] == manufacturing_finding
    assert result["decision"]["recommended_action_type"] == "expedite_shipment"
    assert any(o["action_type"] == "emergency_po" for o in result["candidate_options"])

    case = db.get(Case, "CASE-1")
    assert case.status == "PENDING_APPROVAL"
    assert json.loads(case.findings_json)["demand"] == demand_finding

    approval = db.query(Approval).filter_by(case_id="CASE-1").one()
    assert approval.status == "PENDING"
