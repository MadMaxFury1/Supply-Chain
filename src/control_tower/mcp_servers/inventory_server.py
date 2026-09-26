"""Inventory MCP - read-only access to inventory positions, demand
forecasts and open purchase orders. Used by the Demand and Inventory
investigation agents. No write tools live here (least privilege: nothing
on this server can mutate enterprise state).

Run standalone: python -m control_tower.mcp_servers.inventory_server
"""
from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from control_tower.audit.trail import record_event
from control_tower.db.models import DemandForecast, InventoryPosition, PurchaseOrder
from control_tower.db.session import get_session

ACTOR = "inventory_mcp"

server = MCPServer(
    name="inventory-mcp",
    version="0.1.0",
    instructions=(
        "Read-only tools over the synthetic pharma dataset: current inventory "
        "positions, demand forecast history, and open/delayed purchase orders."
    ),
)


class InventoryPositionOut(BaseModel):
    product_id: str
    site_id: str
    on_hand_qty: float
    safety_stock_qty: float
    unit_of_measure: str
    as_of_date: date


class DemandForecastPoint(BaseModel):
    period: date
    forecast_qty: float
    actual_qty: float | None


class PurchaseOrderOut(BaseModel):
    po_id: str
    product_id: str
    supplier_id: str
    qty: float
    status: str
    promised_date: date
    expected_date: date


@server.tool()
def get_inventory_position(product_id: str, site_id: str, case_id: str | None = None) -> InventoryPositionOut:
    """Return the most recent on-hand / safety-stock position for a product at a site."""
    with get_session() as session:
        pos = (
            session.query(InventoryPosition)
            .filter_by(product_id=product_id, site_id=site_id)
            .order_by(InventoryPosition.as_of_date.desc())
            .first()
        )
        payload = {"product_id": product_id, "site_id": site_id}
        if pos is None:
            record_event(session, case_id, ACTOR, "get_inventory_position", payload, "ERROR")
            raise ToolError(f"no inventory position found for product={product_id!r} site={site_id!r}")

        record_event(session, case_id, ACTOR, "get_inventory_position", payload, "SUCCESS")
        return InventoryPositionOut(
            product_id=pos.product_id,
            site_id=pos.site_id,
            on_hand_qty=pos.on_hand_qty,
            safety_stock_qty=pos.safety_stock_qty,
            unit_of_measure=pos.unit_of_measure,
            as_of_date=pos.as_of_date,
        )


@server.tool()
def list_inventory_positions(
    product_id: str, exclude_site_id: str | None = None, case_id: str | None = None
) -> list[InventoryPositionOut]:
    """Return the most recent position at every site for a product, optionally excluding one site."""
    with get_session() as session:
        rows = (
            session.query(InventoryPosition)
            .filter(InventoryPosition.product_id == product_id)
            .order_by(InventoryPosition.site_id, InventoryPosition.as_of_date.desc())
            .all()
        )
        latest_by_site: dict[str, InventoryPosition] = {}
        for row in rows:
            latest_by_site.setdefault(row.site_id, row)
        if exclude_site_id is not None:
            latest_by_site.pop(exclude_site_id, None)

        record_event(
            session, case_id, ACTOR, "list_inventory_positions",
            {"product_id": product_id, "exclude_site_id": exclude_site_id}, "SUCCESS",
        )
        return [
            InventoryPositionOut(
                product_id=pos.product_id,
                site_id=pos.site_id,
                on_hand_qty=pos.on_hand_qty,
                safety_stock_qty=pos.safety_stock_qty,
                unit_of_measure=pos.unit_of_measure,
                as_of_date=pos.as_of_date,
            )
            for pos in latest_by_site.values()
        ]


@server.tool()
def get_demand_forecast(
    product_id: str, site_id: str, months: int = 6, case_id: str | None = None
) -> list[DemandForecastPoint]:
    """Return up to `months` of forecast-vs-actual demand history, most recent last."""
    with get_session() as session:
        rows = (
            session.query(DemandForecast)
            .filter_by(product_id=product_id, site_id=site_id)
            .order_by(DemandForecast.period.desc())
            .limit(months)
            .all()
        )
        payload = {"product_id": product_id, "site_id": site_id, "months": months}
        if not rows:
            record_event(session, case_id, ACTOR, "get_demand_forecast", payload, "ERROR")
            raise ToolError(f"no demand history for product={product_id!r} site={site_id!r}")

        record_event(session, case_id, ACTOR, "get_demand_forecast", payload, "SUCCESS")
        return [
            DemandForecastPoint(period=r.period, forecast_qty=r.forecast_qty, actual_qty=r.actual_qty)
            for r in reversed(rows)
        ]


@server.tool()
def get_open_purchase_orders(product_id: str, case_id: str | None = None) -> list[PurchaseOrderOut]:
    """Return open or delayed purchase orders for a product (empty list if none)."""
    with get_session() as session:
        rows = (
            session.query(PurchaseOrder)
            .filter(PurchaseOrder.product_id == product_id, PurchaseOrder.status.in_(("OPEN", "DELAYED")))
            .all()
        )
        record_event(
            session, case_id, ACTOR, "get_open_purchase_orders",
            {"product_id": product_id}, "SUCCESS",
        )
        return [
            PurchaseOrderOut(
                po_id=r.po_id, product_id=r.product_id, supplier_id=r.supplier_id, qty=r.qty,
                status=r.status, promised_date=r.promised_date, expected_date=r.expected_date,
            )
            for r in rows
        ]


if __name__ == "__main__":
    import asyncio

    asyncio.run(server.run_stdio_async())
