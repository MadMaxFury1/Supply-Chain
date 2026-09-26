from datetime import date, timedelta

from control_tower.db.models import DemandForecast, InventoryPosition, Product, PurchaseOrder, Site, Supplier
from control_tower.domain.risk_detector import detect_stockout_risks

TODAY = date(2026, 9, 26)


def _seed_common(db):
    db.add_all([
        Site(site_id="SITE-1", name="Test DC", site_type="DC", country="USA"),
        Supplier(supplier_id="SUP-1", name="Test Supplier", reliability_score=0.9, country="USA"),
    ])
    db.flush()


def test_detects_new_at_risk_case(db):
    _seed_common(db)
    db.add(Product(product_id="PRD-1", name="RiskyDrug", ndc_code="1-1-1", dosage_form="Tablet",
                    therapeutic_area="Oncology", is_critical=True))
    db.flush()
    db.add(InventoryPosition(product_id="PRD-1", site_id="SITE-1", on_hand_qty=50,
                              safety_stock_qty=100, unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="PRD-1", site_id="SITE-1", period=date(2026, 9, 1),
                           forecast_qty=300, actual_qty=900))  # 30/day -> 50/30=1.67 days of supply
    db.flush()

    cases = detect_stockout_risks(db, today=TODAY)

    assert len(cases) == 1
    case = cases[0]
    assert case.product_id == "PRD-1"
    assert case.site_id == "SITE-1"
    assert case.status == "OPEN"
    assert case.days_of_supply < 5


def test_healthy_product_not_flagged(db):
    _seed_common(db)
    db.add(Product(product_id="PRD-2", name="HealthyDrug", ndc_code="1-1-2", dosage_form="Tablet",
                    therapeutic_area="Cardiology", is_critical=True))
    db.flush()
    db.add(InventoryPosition(product_id="PRD-2", site_id="SITE-1", on_hand_qty=3000,
                              safety_stock_qty=200, unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="PRD-2", site_id="SITE-1", period=date(2026, 9, 1),
                           forecast_qty=300, actual_qty=300))
    db.flush()

    cases = detect_stockout_risks(db, today=TODAY)

    assert cases == []


def test_non_critical_product_ignored(db):
    _seed_common(db)
    db.add(Product(product_id="PRD-3", name="NonCritical", ndc_code="1-1-3", dosage_form="Tablet",
                    therapeutic_area="Cardiology", is_critical=False))
    db.flush()
    db.add(InventoryPosition(product_id="PRD-3", site_id="SITE-1", on_hand_qty=1,
                              safety_stock_qty=100, unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="PRD-3", site_id="SITE-1", period=date(2026, 9, 1),
                           forecast_qty=300, actual_qty=900))
    db.flush()

    cases = detect_stockout_risks(db, today=TODAY)

    assert cases == []


def test_idempotent_when_case_already_open(db):
    _seed_common(db)
    db.add(Product(product_id="PRD-4", name="RiskyDrug2", ndc_code="1-1-4", dosage_form="Tablet",
                    therapeutic_area="Oncology", is_critical=True))
    db.flush()
    db.add(InventoryPosition(product_id="PRD-4", site_id="SITE-1", on_hand_qty=50,
                              safety_stock_qty=100, unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="PRD-4", site_id="SITE-1", period=date(2026, 9, 1),
                           forecast_qty=300, actual_qty=900))
    db.flush()

    first_run = detect_stockout_risks(db, today=TODAY)
    second_run = detect_stockout_risks(db, today=TODAY)

    assert len(first_run) == 1
    assert second_run == []


def test_lead_time_from_open_purchase_order(db):
    _seed_common(db)
    db.add(Product(product_id="PRD-5", name="RiskyDrug3", ndc_code="1-1-5", dosage_form="Tablet",
                    therapeutic_area="Oncology", is_critical=True))
    db.flush()
    db.add(InventoryPosition(product_id="PRD-5", site_id="SITE-1", on_hand_qty=500,
                              safety_stock_qty=100, unit_of_measure="units", as_of_date=TODAY))
    db.add(DemandForecast(product_id="PRD-5", site_id="SITE-1", period=date(2026, 9, 1),
                           forecast_qty=300, actual_qty=300))  # 10/day -> 50 days of supply, healthy on its own
    db.add(PurchaseOrder(po_id="PO-1", product_id="PRD-5", supplier_id="SUP-1", qty=500, status="DELAYED",
                          promised_date=TODAY - timedelta(days=10), expected_date=TODAY + timedelta(days=60)))
    db.flush()

    cases = detect_stockout_risks(db, today=TODAY)

    # 50 days of supply < 60-day lead time + 7-day buffer -> at risk despite healthy stock in isolation
    assert len(cases) == 1
