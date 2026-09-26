"""Manufacturing MCP - manufacturing-order status (read-only), used by the
Manufacturing investigation agent. Home for manufacturing-domain tools
going forward (later Phase 2 agents - Capacity, Material Availability,
Scheduling - add their tools here too).

Run standalone: python -m control_tower.mcp_servers.manufacturing_server
"""
from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from control_tower.audit.trail import record_event
from control_tower.db.models import ManufacturingOrder
from control_tower.db.session import get_session

ACTOR = "manufacturing_mcp"

server = MCPServer(
    name="manufacturing-mcp",
    version="0.1.0",
    instructions="Manufacturing order status (read-only).",
)


class ManufacturingOrderOut(BaseModel):
    mo_id: str
    product_id: str
    site_id: str
    planned_qty: float
    status: str
    planned_completion_date: date


@server.tool()
def get_manufacturing_status(product_id: str, case_id: str | None = None) -> list[ManufacturingOrderOut]:
    """Return manufacturing orders in flight for a product (empty list if none)."""
    with get_session() as session:
        rows = session.query(ManufacturingOrder).filter_by(product_id=product_id).all()
        record_event(session, case_id, ACTOR, "get_manufacturing_status", {"product_id": product_id}, "SUCCESS")
        return [
            ManufacturingOrderOut(
                mo_id=r.mo_id, product_id=r.product_id, site_id=r.site_id, planned_qty=r.planned_qty,
                status=r.status, planned_completion_date=r.planned_completion_date,
            )
            for r in rows
        ]


if __name__ == "__main__":
    import asyncio

    asyncio.run(server.run_stdio_async())
