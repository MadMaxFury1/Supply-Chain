"""Deterministic stockout-risk detection.

Per CLAUDE.md Principle 3 ("deterministic logic stays outside the LLM") and
the Do-Not rule against creating an agent where a deterministic service is
sufficient, this is plain code - no LLM call. It scans critical products for
thin days-of-supply relative to incoming lead time and opens a Case when a
new risk is found. It will not reopen a case for a product/site that already
has one in flight.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from control_tower.config import DEFAULT_LEAD_TIME_DAYS, DEFAULT_SAFETY_BUFFER_DAYS
from control_tower.db.models import (
    Case,
    DemandForecast,
    InventoryPosition,
    Product,
    PurchaseOrder,
    utcnow,
)
from control_tower.hooks import on_case_opened

OPEN_CASE_STATUSES = ("OPEN", "INVESTIGATING", "PENDING_APPROVAL", "APPROVED", "EXECUTING")


@dataclass
class RiskAssessment:
    product_id: str
    site_id: str
    on_hand_qty: float
    avg_daily_demand: float
    days_of_supply: float
    lead_time_days: float
    risk_threshold_days: float
    risk_score: float
    at_risk: bool


def _avg_daily_demand(session: Session, product_id: str, site_id: str) -> float:
    """Most recent month's actual demand / 30 - responsive to a fresh spike."""
    latest = (
        session.execute(
            select(DemandForecast)
            .where(DemandForecast.product_id == product_id, DemandForecast.site_id == site_id)
            .order_by(DemandForecast.period.desc())
        )
        .scalars()
        .first()
    )
    if latest is None or not latest.actual_qty:
        return 0.0
    return latest.actual_qty / 30.0


def _incoming_lead_time_days(session: Session, product_id: str, today: date) -> float:
    """Days until the nearest open/delayed PO is expected; default lead time if none."""
    open_pos = (
        session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.product_id == product_id,
                PurchaseOrder.status.in_(("OPEN", "DELAYED")),
            )
        )
        .scalars()
        .all()
    )
    if not open_pos:
        return float(DEFAULT_LEAD_TIME_DAYS)
    soonest = min((po.expected_date - today).days for po in open_pos)
    return float(max(soonest, 0))


def assess_product_site(session: Session, product_id: str, site_id: str, today: date | None = None) -> RiskAssessment:
    today = today or date.today()

    position = (
        session.execute(
            select(InventoryPosition)
            .where(InventoryPosition.product_id == product_id, InventoryPosition.site_id == site_id)
            .order_by(InventoryPosition.as_of_date.desc())
        )
        .scalars()
        .first()
    )
    on_hand = position.on_hand_qty if position else 0.0

    avg_demand = _avg_daily_demand(session, product_id, site_id)
    lead_time = _incoming_lead_time_days(session, product_id, today)
    threshold = lead_time + DEFAULT_SAFETY_BUFFER_DAYS

    days_of_supply = (on_hand / avg_demand) if avg_demand > 0 else float("inf")
    risk_score = round(threshold / days_of_supply, 3) if days_of_supply > 0 else float("inf")
    at_risk = days_of_supply < threshold

    return RiskAssessment(
        product_id=product_id,
        site_id=site_id,
        on_hand_qty=on_hand,
        avg_daily_demand=avg_demand,
        days_of_supply=round(days_of_supply, 2) if days_of_supply != float("inf") else days_of_supply,
        lead_time_days=lead_time,
        risk_threshold_days=threshold,
        risk_score=risk_score,
        at_risk=at_risk,
    )


def _has_open_case(session: Session, product_id: str, site_id: str) -> bool:
    existing = session.execute(
        select(Case).where(
            Case.product_id == product_id,
            Case.site_id == site_id,
            Case.status.in_(OPEN_CASE_STATUSES),
        )
    ).scalars().first()
    return existing is not None


def detect_stockout_risks(session: Session, today: date | None = None) -> list[Case]:
    """Scan all critical product/site combinations and open new Cases for
    those newly crossing the stockout-risk threshold. Returns the cases
    created in this run (idempotent - skips product/sites with a case
    already in flight)."""
    today = today or date.today()
    new_cases: list[Case] = []

    critical_products = session.execute(select(Product).where(Product.is_critical)).scalars().all()
    for product in critical_products:
        site_ids = {
            row[0]
            for row in session.execute(
                select(InventoryPosition.site_id).where(InventoryPosition.product_id == product.product_id)
            ).all()
        }
        for site_id in site_ids:
            if _has_open_case(session, product.product_id, site_id):
                continue

            assessment = assess_product_site(session, product.product_id, site_id, today)
            if not assessment.at_risk:
                continue

            case = Case(
                case_id=f"CASE-{uuid4().hex[:8].upper()}",
                product_id=product.product_id,
                site_id=site_id,
                status="OPEN",
                risk_score=assessment.risk_score,
                days_of_supply=assessment.days_of_supply,
                detected_at=utcnow(),
            )
            session.add(case)
            new_cases.append(case)
            on_case_opened(case.case_id, case.product_id, case.site_id, case.risk_score)

    session.flush()
    return new_cases
