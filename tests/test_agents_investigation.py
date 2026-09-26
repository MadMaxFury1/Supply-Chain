"""Agent-behavior tests for the Demand/Inventory/Supply investigation agents.

These stub the LLM (`llm_call`) with scripted tool-use then final-answer
responses, so they exercise the real ToolCallingAgent loop and real MCP
tools/guardrails against a test DB, without making real Anthropic API calls.
"""
import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

from control_tower.agents.base import InProcessToolDispatcher
from control_tower.agents.demand_agent import run_demand_agent
from control_tower.agents.inventory_agent import run_inventory_agent
from control_tower.agents.manufacturing_agent import run_manufacturing_agent
from control_tower.agents.reallocation_scout_agent import run_reallocation_scout
from control_tower.agents.supply_agent import run_supply_agent
from control_tower.db.models import (
    DemandForecast,
    InventoryPosition,
    ManufacturingOrder,
    PurchaseOrder,
    Supplier,
)

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


def test_demand_agent_flags_spike(db):
    db.add(DemandForecast(product_id="P1", site_id="S1", period=date(2026, 8, 1), forecast_qty=100, actual_qty=95))
    db.add(DemandForecast(product_id="P1", site_id="S1", period=date(2026, 9, 1), forecast_qty=100, actual_qty=260))
    db.commit()

    finding = {
        "cause_category": "demand_spike",
        "evidence": "Latest month actual demand of 260 is 2.6x the forecast of 100.",
        "confidence": 0.9,
        "contributes": True,
    }
    llm_call = _scripted_llm_call([
        _tool_use_response("get_demand_forecast", {"product_id": "P1", "site_id": "S1", "months": 6}),
        _text_response(finding),
    ])

    result = asyncio.run(
        run_demand_agent(InProcessToolDispatcher(), "CASE-1", "P1", "S1", llm_call=llm_call)
    )

    assert result == finding


def test_inventory_agent_flags_thin_stock_and_attaches_reallocation_signal(db):
    db.add(InventoryPosition(product_id="P1", site_id="S1", on_hand_qty=50, safety_stock_qty=150,
                              unit_of_measure="units", as_of_date=TODAY))
    # S2 has surplus - the Reallocation Scout sub-agent should surface it as
    # an advisory signal, not as a new mitigation action.
    db.add(InventoryPosition(product_id="P1", site_id="S2", on_hand_qty=400, safety_stock_qty=100,
                              unit_of_measure="units", as_of_date=TODAY))
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY - timedelta(days=10), expected_date=TODAY + timedelta(days=20)))
    db.commit()

    finding = {
        "cause_category": "thin_safety_stock",
        "evidence": "On-hand is 50 against a safety stock target of 150, and the only open PO is delayed.",
        "confidence": 0.85,
        "contributes": True,
    }
    scout_finding = {
        "available": True,
        "evidence": "Site S2 has 300 units of on-hand stock above its own safety stock target.",
        "candidate_sites": ["S2"],
        "confidence": 0.75,
    }
    llm_call = _scripted_llm_call([
        _tool_use_response("get_inventory_position", {"product_id": "P1", "site_id": "S1"}, "tu_1"),
        _tool_use_response("get_open_purchase_orders", {"product_id": "P1"}, "tu_2"),
        _text_response(finding),
        _tool_use_response("list_inventory_positions", {"product_id": "P1", "exclude_site_id": "S1"}, "tu_1"),
        _text_response(scout_finding),
    ])

    result = asyncio.run(
        run_inventory_agent(InProcessToolDispatcher(), "CASE-1", "P1", "S1", llm_call=llm_call)
    )

    assert result["reallocation_signal"] == scout_finding
    assert {k: v for k, v in result.items() if k != "reallocation_signal"} == finding


def test_reallocation_scout_finds_surplus_elsewhere(db):
    db.add(InventoryPosition(product_id="P1", site_id="S2", on_hand_qty=400, safety_stock_qty=100,
                              unit_of_measure="units", as_of_date=TODAY))
    db.commit()

    scout_finding = {
        "available": True,
        "evidence": "Site S2 has 300 units of on-hand stock above its own safety stock target.",
        "candidate_sites": ["S2"],
        "confidence": 0.75,
    }
    llm_call = _scripted_llm_call([
        _tool_use_response("list_inventory_positions", {"product_id": "P1", "exclude_site_id": "S1"}, "tu_1"),
        _text_response(scout_finding),
    ])

    result = asyncio.run(
        run_reallocation_scout(InProcessToolDispatcher(), "CASE-1", "P1", "S1", llm_call=llm_call)
    )

    assert result == scout_finding


def test_inventory_agent_survives_reallocation_scout_failure(db):
    db.add(InventoryPosition(product_id="P1", site_id="S1", on_hand_qty=50, safety_stock_qty=150,
                              unit_of_measure="units", as_of_date=TODAY))
    db.add(PurchaseOrder(po_id="PO-1", product_id="P1", supplier_id="SUP-1", qty=100, status="DELAYED",
                          promised_date=TODAY - timedelta(days=10), expected_date=TODAY + timedelta(days=20)))
    db.commit()

    finding = {
        "cause_category": "thin_safety_stock",
        "evidence": "On-hand is 50 against a safety stock target of 150, and the only open PO is delayed.",
        "confidence": 0.85,
        "contributes": True,
    }
    # Scout never reaches a final answer within its max_turns=3 -> RuntimeError,
    # which the parent must swallow rather than propagate or lose its own finding.
    llm_call = _scripted_llm_call([
        _tool_use_response("get_inventory_position", {"product_id": "P1", "site_id": "S1"}, "tu_1"),
        _tool_use_response("get_open_purchase_orders", {"product_id": "P1"}, "tu_2"),
        _text_response(finding),
        _tool_use_response("list_inventory_positions", {"product_id": "P1", "exclude_site_id": "S1"}, "tu_1"),
        _tool_use_response("list_inventory_positions", {"product_id": "P1", "exclude_site_id": "S1"}, "tu_2"),
        _tool_use_response("list_inventory_positions", {"product_id": "P1", "exclude_site_id": "S1"}, "tu_3"),
    ])

    result = asyncio.run(
        run_inventory_agent(InProcessToolDispatcher(), "CASE-1", "P1", "S1", llm_call=llm_call)
    )

    assert result == finding
    assert "reallocation_signal" not in result


def test_supply_agent_flags_unreliable_supplier(db):
    db.add(Supplier(supplier_id="SUP-1", name="Flaky Co", reliability_score=0.4, country="IN"))
    db.commit()

    finding = {
        "cause_category": "unreliable_supplier",
        "evidence": "Supplier reliability score is 0.4.",
        "confidence": 0.8,
        "contributes": True,
    }
    llm_call = _scripted_llm_call([
        _tool_use_response("get_supplier_status", {"supplier_id": "SUP-1"}, "tu_1"),
        _text_response(finding),
    ])

    result = asyncio.run(
        run_supply_agent(InProcessToolDispatcher(), "CASE-1", "P1", "SUP-1", llm_call=llm_call)
    )

    assert result == finding


def test_manufacturing_agent_flags_delayed_mo(db):
    db.add(ManufacturingOrder(mo_id="MO-1", product_id="P1", site_id="PLANT-1", planned_qty=500,
                               status="DELAYED", planned_completion_date=TODAY + timedelta(days=5)))
    db.commit()

    finding = {
        "cause_category": "manufacturing_delay",
        "evidence": "Manufacturing order MO-1 for this product is delayed, planned completion in 5 days.",
        "confidence": 0.8,
        "contributes": True,
    }
    llm_call = _scripted_llm_call([
        _tool_use_response("get_manufacturing_status", {"product_id": "P1"}, "tu_1"),
        _text_response(finding),
    ])

    result = asyncio.run(
        run_manufacturing_agent(InProcessToolDispatcher(), "CASE-1", "P1", llm_call=llm_call)
    )

    assert result == finding


def test_agent_reports_not_contributing_without_tool_call(db):
    finding = {"cause_category": "none", "evidence": "no data reviewed", "confidence": 0.1, "contributes": False}
    llm_call = _scripted_llm_call([_text_response(finding)])

    result = asyncio.run(
        run_demand_agent(InProcessToolDispatcher(), "CASE-1", "P1", "S1", llm_call=llm_call)
    )

    assert result["contributes"] is False
