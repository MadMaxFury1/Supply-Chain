#!/usr/bin/env python3
"""Generate a synthetic life-sciences enterprise dataset for the Phase 1
stockout vertical slice.

Produces ~40 products across a handful of sites and suppliers with six
months of demand history and current inventory - all healthy - plus one
deliberately seeded stockout scenario (a critical product with a demand
spike, a delayed supplier PO, and thin safety stock at one site) so the
detection -> investigation -> decision -> approval -> execution pipeline
has a concrete, reproducible case to run end to end.

Usage: python scripts/generate_synthetic_data.py [--reset]
"""
import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from faker import Faker

from control_tower.db.models import (
    DemandForecast,
    InventoryPosition,
    ManufacturingOrder,
    Product,
    PurchaseOrder,
    Shipment,
    Site,
    Supplier,
)
from control_tower.db.session import get_session, init_db

SEED = 42
TODAY = date.today()

THERAPEUTIC_AREAS = [
    "Oncology", "Cardiology", "Immunology", "Neurology",
    "Infectious Disease", "Endocrinology", "Respiratory",
]
DOSAGE_FORMS = ["Tablet", "Capsule", "Injectable", "Infusion Bag", "Prefilled Syringe"]

SEEDED_PRODUCT_ID = "PRD-0001"
SEEDED_SITE_ID = "SITE-DC-01"
SEEDED_SUPPLIER_ID = "SUP-03"


def month_starts(n_months: int) -> list[date]:
    months = []
    y, m = TODAY.year, TODAY.month
    for i in range(n_months, 0, -1):
        mm = m - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append(date(yy, mm, 1))
    return months


def build_sites() -> list[Site]:
    sites = [
        Site(site_id="SITE-DC-01", name="Northeast Distribution Center", site_type="DC", country="USA"),
        Site(site_id="SITE-DC-02", name="Rotterdam Distribution Center", site_type="DC", country="Netherlands"),
        Site(site_id="SITE-DC-03", name="Singapore Distribution Center", site_type="DC", country="Singapore"),
        Site(site_id="SITE-PL-01", name="Raleigh Manufacturing Plant", site_type="PLANT", country="USA"),
        Site(site_id="SITE-PL-02", name="Cork Manufacturing Plant", site_type="PLANT", country="Ireland"),
    ]
    return sites


def build_suppliers(fake: Faker) -> list[Supplier]:
    suppliers = []
    countries = ["USA", "Germany", "India", "Switzerland", "Ireland", "China", "Japan", "France"]
    for i in range(1, 9):
        supplier_id = f"SUP-{i:02d}"
        reliability = round(random.uniform(0.75, 0.98), 2)
        if supplier_id == SEEDED_SUPPLIER_ID:
            reliability = 0.52  # deliberately unreliable
        suppliers.append(
            Supplier(
                supplier_id=supplier_id,
                name=fake.company() + " Pharma Ingredients",
                reliability_score=reliability,
                country=random.choice(countries),
            )
        )
    return suppliers


def build_products(fake: Faker, n: int) -> list[Product]:
    products = []
    for i in range(1, n + 1):
        product_id = f"PRD-{i:04d}"
        is_critical = (i % 6 == 0) or product_id == SEEDED_PRODUCT_ID
        products.append(
            Product(
                product_id=product_id,
                name=f"{fake.word().capitalize()}{fake.word().capitalize()} {random.choice([5, 10, 25, 50, 100])}mg",
                ndc_code=f"{random.randint(10000,99999)}-{random.randint(100,999)}-{random.randint(10,99)}",
                dosage_form=random.choice(DOSAGE_FORMS),
                therapeutic_area=random.choice(THERAPEUTIC_AREAS),
                is_critical=is_critical,
            )
        )
    products[0].product_id = SEEDED_PRODUCT_ID
    products[0].name = "OncoStat 50mg"
    products[0].therapeutic_area = "Oncology"
    products[0].dosage_form = "Infusion Bag"
    products[0].is_critical = True
    return products


def build_demand_and_inventory(products: list[Product], sites: list[Site]):
    forecasts, positions = [], []
    months = month_starts(6)
    dc_sites = [s for s in sites if s.site_type == "DC"]

    for product in products:
        assigned_sites = random.sample(dc_sites, k=random.choice([1, 2]))
        if product.product_id == SEEDED_PRODUCT_ID and not any(
            s.site_id == SEEDED_SITE_ID for s in assigned_sites
        ):
            assigned_sites[0] = next(s for s in sites if s.site_id == SEEDED_SITE_ID)

        for site in assigned_sites:
            base_demand = random.uniform(80, 400)
            for idx, period in enumerate(months):
                forecast_qty = round(base_demand * random.uniform(0.9, 1.1), 1)
                actual_qty = round(forecast_qty * random.uniform(0.85, 1.15), 1)

                is_seeded_case = (
                    product.product_id == SEEDED_PRODUCT_ID and site.site_id == SEEDED_SITE_ID
                )
                if is_seeded_case and idx == len(months) - 1:
                    # Demand spike in the most recent month (e.g. outbreak-driven surge)
                    forecast_qty = round(base_demand, 1)
                    actual_qty = round(base_demand * 2.6, 1)

                forecasts.append(
                    DemandForecast(
                        product_id=product.product_id,
                        site_id=site.site_id,
                        period=period,
                        forecast_qty=forecast_qty,
                        actual_qty=actual_qty,
                    )
                )

            if product.product_id == SEEDED_PRODUCT_ID and site.site_id == SEEDED_SITE_ID:
                on_hand = round(base_demand * 0.35, 1)  # well under a month of (pre-spike) demand
                safety_stock = round(base_demand * 0.5, 1)
            else:
                on_hand = round(base_demand * random.uniform(1.8, 3.5), 1)
                safety_stock = round(base_demand * random.uniform(0.4, 0.6), 1)

            positions.append(
                InventoryPosition(
                    product_id=product.product_id,
                    site_id=site.site_id,
                    on_hand_qty=on_hand,
                    safety_stock_qty=safety_stock,
                    unit_of_measure="units",
                    as_of_date=TODAY,
                )
            )
    return forecasts, positions


def build_supply_side(products: list[Product], suppliers: list[Supplier], sites: list[Site]):
    pos, mos, shipments = [], [], []
    plant_sites = [s for s in sites if s.site_type == "PLANT"]
    po_counter = 1
    mo_counter = 1
    shipment_counter = 1

    for product in products:
        supplier = random.choice(suppliers)
        qty = round(random.uniform(500, 3000), 0)
        promised_date = TODAY - timedelta(days=random.randint(0, 10))
        expected_date = promised_date + timedelta(days=random.randint(0, 3))
        status = "OPEN"

        is_seeded_case = product.product_id == SEEDED_PRODUCT_ID
        if is_seeded_case:
            supplier = next(s for s in suppliers if s.supplier_id == SEEDED_SUPPLIER_ID)
            qty = 1200
            promised_date = TODAY - timedelta(days=18)
            expected_date = TODAY + timedelta(days=27)  # badly delayed
            status = "DELAYED"

        po_id = f"PO-{po_counter:05d}"
        po_counter += 1
        pos.append(
            PurchaseOrder(
                po_id=po_id,
                product_id=product.product_id,
                supplier_id=supplier.supplier_id,
                qty=qty,
                status=status,
                promised_date=promised_date,
                expected_date=expected_date,
            )
        )

        if random.random() < 0.4 or is_seeded_case:
            plant = random.choice(plant_sites)
            mo_status = "DELAYED" if is_seeded_case else random.choice(
                ["SCHEDULED", "IN_PROGRESS", "COMPLETE"]
            )
            planned_completion = (
                TODAY + timedelta(days=30) if is_seeded_case
                else TODAY + timedelta(days=random.randint(-10, 20))
            )
            mo_id = f"MO-{mo_counter:05d}"
            mo_counter += 1
            mos.append(
                ManufacturingOrder(
                    mo_id=mo_id,
                    product_id=product.product_id,
                    site_id=plant.site_id,
                    planned_qty=round(random.uniform(500, 2000), 0),
                    status=mo_status,
                    planned_completion_date=planned_completion,
                )
            )

        if status != "CANCELLED":
            shipment_id = f"SHP-{shipment_counter:05d}"
            shipment_counter += 1
            shipments.append(
                Shipment(
                    shipment_id=shipment_id,
                    reference_type="PO",
                    reference_id=po_id,
                    carrier=random.choice(["DHL", "FedEx", "Kuehne+Nagel", "DB Schenker"]),
                    status="DELAYED" if is_seeded_case else "IN_TRANSIT",
                    origin=supplier.country,
                    destination="USA",
                    eta=expected_date,
                )
            )
    return pos, mos, shipments


def export_csvs(out_dir: Path, tables: dict[str, list]) -> None:
    """Write each in-memory table to a CSV under out_dir, one file per table -
    the same shape the dashboard's upload feature expects back."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, records in tables.items():
        columns = [c.name for c in records[0].__table__.columns] if records else []
        rows = [{col: getattr(r, col) for col in columns} for r in records]
        pd.DataFrame(rows, columns=columns).to_csv(out_dir / f"{filename}.csv", index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    parser.add_argument("--n-products", type=int, default=40)
    args = parser.parse_args()

    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    init_db(drop_existing=args.reset)

    sites = build_sites()
    suppliers = build_suppliers(fake)
    products = build_products(fake, args.n_products)
    forecasts, positions = build_demand_and_inventory(products, sites)
    pos, mos, shipments = build_supply_side(products, suppliers, sites)

    with get_session() as session:
        session.add_all(sites)
        session.add_all(suppliers)
        session.add_all(products)
        session.flush()
        session.add_all(forecasts)
        session.add_all(positions)
        session.add_all(pos)
        session.add_all(mos)
        session.add_all(shipments)
        session.flush()  # assign autoincrement ids before the session closes/expires them

        test_data_dir = Path(__file__).resolve().parents[1] / "test data"
        export_csvs(
            test_data_dir,
            {
                "sites": sites,
                "suppliers": suppliers,
                "products": products,
                "demand_forecast": forecasts,
                "inventory_positions": positions,
                "purchase_orders": pos,
                "manufacturing_orders": mos,
                "shipments": shipments,
            },
        )
    print(f"Wrote CSV exports to {test_data_dir}/")

    print(f"Generated synthetic dataset:")
    print(f"  products:            {len(products)}")
    print(f"  sites:               {len(sites)}")
    print(f"  suppliers:           {len(suppliers)}")
    print(f"  demand_forecast:     {len(forecasts)}")
    print(f"  inventory_positions: {len(positions)}")
    print(f"  purchase_orders:     {len(pos)}")
    print(f"  manufacturing_orders:{len(mos)}")
    print(f"  shipments:           {len(shipments)}")
    print(f"\nSeeded stockout scenario: product={SEEDED_PRODUCT_ID} site={SEEDED_SITE_ID} "
          f"supplier={SEEDED_SUPPLIER_ID}")


if __name__ == "__main__":
    main()
