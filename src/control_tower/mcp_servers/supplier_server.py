"""Supplier MCP - supplier reliability/profile status (used by the Supply
investigation agent) plus the only two write/execution tools in the whole
system: create_expedite_shipment and create_emergency_po. These are the
sole capability boundary an Execution Agent can act through.

Every write tool re-validates Guardrail Gate B against the DB *inside the
handler* before mutating anything - this is the actual enforcement point,
not a suggestion the caller could skip. See control_tower.guardrails.policy.

Manufacturing order status lives in manufacturing_server.py, not here -
see that module's docstring for why the two are kept separate.

Run standalone: python -m control_tower.mcp_servers.supplier_server
"""
from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from control_tower.audit.trail import record_event
from control_tower.db.models import PurchaseOrder, Shipment, Supplier
from control_tower.db.session import get_session
from control_tower.guardrails.policy import gate_b_pre_execution

ACTOR = "supplier_mcp"

server = MCPServer(
    name="supplier-mcp",
    version="0.1.0",
    instructions=(
        "Supplier status (read-only), plus guardrail-gated mitigation "
        "execution tools: create_expedite_shipment, create_emergency_po."
    ),
)


class SupplierStatusOut(BaseModel):
    supplier_id: str
    name: str
    reliability_score: float
    country: str


class ExecutionResult(BaseModel):
    approval_id: str
    action_type: str
    status: str  # EXECUTED | DENIED
    detail: str
    reference_id: str | None = None


@server.tool()
def get_supplier_status(supplier_id: str, case_id: str | None = None) -> SupplierStatusOut:
    """Return reliability and profile info for a supplier."""
    with get_session() as session:
        supplier = session.get(Supplier, supplier_id)
        if supplier is None:
            record_event(session, case_id, ACTOR, "get_supplier_status", {"supplier_id": supplier_id}, "ERROR")
            raise ToolError(f"unknown supplier_id {supplier_id!r}")
        record_event(session, case_id, ACTOR, "get_supplier_status", {"supplier_id": supplier_id}, "SUCCESS")
        return SupplierStatusOut(
            supplier_id=supplier.supplier_id, name=supplier.name,
            reliability_score=supplier.reliability_score, country=supplier.country,
        )


def _deny(session, case_id, action_type, reason) -> ExecutionResult:
    record_event(session, case_id, ACTOR, action_type, {"reason": reason}, "DENIED")
    raise ToolError(f"guardrail denied {action_type}: {reason}")


@server.tool()
def create_expedite_shipment(approval_id: str, po_id: str, case_id: str) -> ExecutionResult:
    """Execute an approved 'expedite_shipment' mitigation: mark the PO and its
    shipment as expedited with a pulled-forward ETA. Requires a matching
    APPROVED approval (Guardrail Gate B) - fails closed otherwise."""
    with get_session() as session:
        params = {"po_id": po_id}
        gate = gate_b_pre_execution(session, approval_id, "expedite_shipment", params)
        if not gate.allowed:
            return _deny(session, case_id, "create_expedite_shipment", gate.reason)

        po = session.get(PurchaseOrder, po_id)
        if po is None:
            return _deny(session, case_id, "create_expedite_shipment", f"unknown po_id {po_id!r}")

        po.status = "EXPEDITED"
        new_eta = date.today() + timedelta(days=3)
        po.expected_date = new_eta

        shipment = session.query(Shipment).filter_by(reference_type="PO", reference_id=po_id).first()
        if shipment is not None:
            shipment.status = "EXPEDITED"
            shipment.eta = new_eta

        record_event(
            session, case_id, ACTOR, "create_expedite_shipment",
            {"approval_id": approval_id, "po_id": po_id, "new_eta": str(new_eta)}, "SUCCESS",
        )
        return ExecutionResult(
            approval_id=approval_id, action_type="expedite_shipment", status="EXECUTED",
            detail=f"PO {po_id} expedited, new ETA {new_eta}", reference_id=po_id,
        )


@server.tool()
def create_emergency_po(approval_id: str, supplier_id: str, qty: float, case_id: str) -> ExecutionResult:
    """Execute an approved 'emergency_po' mitigation: raise a new purchase
    order against an (alternate) supplier. Requires a matching APPROVED
    approval (Guardrail Gate B) - fails closed otherwise."""
    with get_session() as session:
        params = {"supplier_id": supplier_id, "qty": qty}
        gate = gate_b_pre_execution(session, approval_id, "emergency_po", params)
        if not gate.allowed:
            return _deny(session, case_id, "create_emergency_po", gate.reason)

        supplier = session.get(Supplier, supplier_id)
        if supplier is None:
            return _deny(session, case_id, "create_emergency_po", f"unknown supplier_id {supplier_id!r}")

        from control_tower.db.models import Case

        case = session.get(Case, case_id)
        po_id = f"PO-EMG-{uuid4().hex[:6].upper()}"
        promised = date.today() + timedelta(days=10)
        expected = date.today() + timedelta(days=14)
        po = PurchaseOrder(
            po_id=po_id, product_id=case.product_id, supplier_id=supplier_id, qty=qty,
            status="OPEN", promised_date=promised, expected_date=expected,
        )
        session.add(po)

        record_event(
            session, case_id, ACTOR, "create_emergency_po",
            {"approval_id": approval_id, "po_id": po_id, "supplier_id": supplier_id, "qty": qty}, "SUCCESS",
        )
        return ExecutionResult(
            approval_id=approval_id, action_type="emergency_po", status="EXECUTED",
            detail=f"Emergency PO {po_id} raised with {supplier_id} for {qty} units, ETA {expected}",
            reference_id=po_id,
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(server.run_stdio_async())
