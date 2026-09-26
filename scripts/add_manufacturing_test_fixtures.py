#!/usr/bin/env python3
"""One-off: add a couple of deliberately-crafted manufacturing_orders rows
for exercising the Manufacturing Agent's edge cases from the dashboard's
Agent Test Bench, without touching the deterministic synthetic-data seed
(`generate_synthetic_data.py --reset` would just regenerate the same fixed
dataset since it uses a fixed random seed - it wouldn't add these).

Idempotent: skips any mo_id that already exists. Re-exports
`test data/manufacturing_orders.csv` afterward so the CSV stays in sync
with the DB (same file the dashboard's upload feature reads/writes).

    python scripts/add_manufacturing_test_fixtures.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from control_tower.db.models import ManufacturingOrder
from control_tower.db.session import get_session

TODAY = date(2026, 9, 26)

FIXTURES = [
    # Severely overdue: single MO, ~45 days past its planned completion date.
    ManufacturingOrder(
        mo_id="MO-00038", product_id="PRD-0008", site_id="SITE-PL-01",
        planned_qty=1200.0, status="DELAYED", planned_completion_date=date(2026, 8, 12),
    ),
    # Conflicting signals on one product: a moderately-overdue MO alongside
    # an already-completed one.
    ManufacturingOrder(
        mo_id="MO-00039", product_id="PRD-0010", site_id="SITE-PL-01",
        planned_qty=900.0, status="DELAYED", planned_completion_date=date(2026, 9, 16),
    ),
    ManufacturingOrder(
        mo_id="MO-00040", product_id="PRD-0010", site_id="SITE-PL-02",
        planned_qty=600.0, status="COMPLETE", planned_completion_date=date(2026, 9, 10),
    ),
]


def main() -> None:
    with get_session() as session:
        existing = {mo_id for (mo_id,) in session.query(ManufacturingOrder.mo_id).all()}
        added_ids = [f.mo_id for f in FIXTURES if f.mo_id not in existing]
        skipped_ids = [f.mo_id for f in FIXTURES if f.mo_id in existing]
        session.add_all(f for f in FIXTURES if f.mo_id not in existing)
        session.flush()

        all_rows = session.query(ManufacturingOrder).order_by(ManufacturingOrder.mo_id).all()
        columns = [c.name for c in ManufacturingOrder.__table__.columns]
        records = [{col: getattr(r, col) for col in columns} for r in all_rows]
        row_count = len(records)

    test_data_dir = Path(__file__).resolve().parents[1] / "test data"
    pd.DataFrame(records, columns=columns).to_csv(test_data_dir / "manufacturing_orders.csv", index=False)

    if added_ids:
        print(f"Added: {', '.join(added_ids)}")
    if skipped_ids:
        print(f"Already present, skipped: {', '.join(skipped_ids)}")
    print(f"Re-exported test data/manufacturing_orders.csv ({row_count} rows total).")


if __name__ == "__main__":
    main()
