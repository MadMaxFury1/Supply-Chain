from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from control_tower.db.models import DemandForecast, InventoryPosition, PurchaseOrder
from control_tower.mcp_servers.inventory_server import (
    get_demand_forecast,
    get_inventory_position,
    get_open_purchase_orders,
    list_inventory_positions,
)

TODAY = date(2026, 9, 26)


def test_get_inventory_position_success(db):
    db.add(InventoryPosition(product_id="P1", site_id="S1", on_hand_qty=100, safety_stock_qty=50,
                              unit_of_measure="units", as_of_date=TODAY))
    db.commit()

    result = get_inventory_position("P1", "S1")

    assert result.product_id == "P1"
    assert result.on_hand_qty == 100


def test_get_inventory_position_unknown_raises(db):
    with pytest.raises(ToolError):
        get_inventory_position("NOPE", "NOWHERE")


def test_list_inventory_positions_excludes_site_and_dedupes_to_latest(db):
    db.add(InventoryPosition(product_id="P1", site_id="S1", on_hand_qty=20, safety_stock_qty=150,
                              unit_of_measure="units", as_of_date=TODAY))
    # S2 has two rows - only the latest as_of_date should be returned.
    db.add(InventoryPosition(product_id="P1", site_id="S2", on_hand_qty=999, safety_stock_qty=100,
                              unit_of_measure="units", as_of_date=date(2026, 8, 1)))
    db.add(InventoryPosition(product_id="P1", site_id="S2", on_hand_qty=400, safety_stock_qty=100,
                              unit_of_measure="units", as_of_date=TODAY))
    db.commit()

    result = list_inventory_positions("P1", exclude_site_id="S1")

    assert [r.site_id for r in result] == ["S2"]
    assert result[0].on_hand_qty == 400


def test_list_inventory_positions_empty_when_none(db):
    result = list_inventory_positions("NOPE")

    assert result == []


def test_get_demand_forecast_orders_oldest_first(db):
    db.add(DemandForecast(product_id="P1", site_id="S1", period=date(2026, 7, 1), forecast_qty=100, actual_qty=90))
    db.add(DemandForecast(product_id="P1", site_id="S1", period=date(2026, 8, 1), forecast_qty=100, actual_qty=95))
    db.commit()

    result = get_demand_forecast("P1", "S1", months=6)

    assert [r.period for r in result] == [date(2026, 7, 1), date(2026, 8, 1)]


def test_get_open_purchase_orders_filters_status(db):
    db.add(PurchaseOrder(po_id="PO1", product_id="P1", supplier_id="SUP1", qty=100, status="OPEN",
                          promised_date=TODAY, expected_date=TODAY))
    db.add(PurchaseOrder(po_id="PO2", product_id="P1", supplier_id="SUP1", qty=50, status="RECEIVED",
                          promised_date=TODAY, expected_date=TODAY))
    db.commit()

    result = get_open_purchase_orders("P1")

    assert [r.po_id for r in result] == ["PO1"]
