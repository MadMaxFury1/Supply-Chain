"""Central configuration. Values are overridable via environment variables."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = Path(os.environ.get("CONTROL_TOWER_DB", str(DATA_DIR / "control_tower.db")))

ANTHROPIC_MODEL = os.environ.get("CONTROL_TOWER_MODEL", "claude-sonnet-5")

# Stockout risk detection thresholds
DEFAULT_LEAD_TIME_DAYS = 21
DEFAULT_SAFETY_BUFFER_DAYS = 7

# Guardrail policy. Phase 1 only implements execution tools for these two
# actions (supplier_mcp.create_expedite_shipment / create_emergency_po); a
# third action (stock_reallocation) is deliberately out of scope for this
# vertical slice since it needs multi-site transfer logic, so it's excluded
# here rather than left as an approvable action with nothing to execute it.
ALLOWED_MITIGATION_ACTIONS = {"expedite_shipment", "emergency_po"}
MAX_EMERGENCY_PO_QTY = 50_000
APPROVAL_EXPIRY_HOURS = 72
