from datetime import date, timedelta

from control_tower.db.models import ManufacturingOrder
from control_tower.mcp_servers.manufacturing_server import get_manufacturing_status

TODAY = date(2026, 9, 26)


def test_get_manufacturing_status(db):
    db.add(ManufacturingOrder(mo_id="MO-1", product_id="P1", site_id="PLANT-1", planned_qty=500,
                               status="DELAYED", planned_completion_date=TODAY))
    db.commit()

    result = get_manufacturing_status("P1")

    assert result[0].status == "DELAYED"


def test_get_manufacturing_status_empty_when_none(db):
    result = get_manufacturing_status("P1")

    assert result == []
