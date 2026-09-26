"""ORM schema for the synthetic life-sciences enterprise dataset plus
control-tower case/approval/audit state. This is the only layer that
touches the database directly - agents never do, they go through MCP tools."""
from __future__ import annotations

from datetime import datetime, date, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC now - datetime.utcnow() is deprecated (3.12+); this keeps
    the same naive-datetime storage/comparison semantics SQLite and the
    rest of the codebase (e.g. guardrails/policy.py's expiry check) rely on."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    ndc_code: Mapped[str] = mapped_column(String, nullable=False)
    dosage_form: Mapped[str] = mapped_column(String, nullable=False)
    therapeutic_area: Mapped[str] = mapped_column(String, nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)


class Site(Base):
    __tablename__ = "sites"

    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    site_type: Mapped[str] = mapped_column(String, nullable=False)  # DC | PLANT
    country: Mapped[str] = mapped_column(String, nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-1
    country: Mapped[str] = mapped_column(String, nullable=False)


class InventoryPosition(Base):
    __tablename__ = "inventory_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"))
    on_hand_qty: Mapped[float] = mapped_column(Float, nullable=False)
    safety_stock_qty: Mapped[float] = mapped_column(Float, nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String, default="units")
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)


class DemandForecast(Base):
    __tablename__ = "demand_forecast"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"))
    period: Mapped[date] = mapped_column(Date, nullable=False)  # first-of-month
    forecast_qty: Mapped[float] = mapped_column(Float, nullable=False)
    actual_qty: Mapped[float] = mapped_column(Float, nullable=True)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    po_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"))
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN|DELAYED|RECEIVED|CANCELLED
    promised_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)


class ManufacturingOrder(Base):
    __tablename__ = "manufacturing_orders"

    mo_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"))
    planned_qty: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="SCHEDULED")  # SCHEDULED|IN_PROGRESS|DELAYED|COMPLETE
    planned_completion_date: Mapped[date] = mapped_column(Date, nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"

    shipment_id: Mapped[str] = mapped_column(String, primary_key=True)
    reference_type: Mapped[str] = mapped_column(String, nullable=False)  # PO|MO|EXPEDITE
    reference_id: Mapped[str] = mapped_column(String, nullable=False)
    carrier: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="IN_TRANSIT")
    origin: Mapped[str] = mapped_column(String, nullable=False)
    destination: Mapped[str] = mapped_column(String, nullable=False)
    eta: Mapped[date] = mapped_column(Date, nullable=False)


class Case(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"))
    status: Mapped[str] = mapped_column(
        String, default="OPEN"
    )  # OPEN|INVESTIGATING|PENDING_APPROVAL|APPROVED|REJECTED|EXECUTING|CLOSED|BLOCKED
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    days_of_supply: Mapped[float] = mapped_column(Float, nullable=False)
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenarios_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"))
    recommended_action_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING|APPROVED|REJECTED
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_log"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # SUCCESS|DENIED|ERROR
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
