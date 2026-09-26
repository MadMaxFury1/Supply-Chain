"""Read-only Streamlit dashboard over the control tower's SQLite DB.

Human-facing reporting UI, not an LLM agent - reads the DB directly via
control_tower.db.session.get_session(), same precedent as risk_detector.py/
guardrails/policy.py/orchestrator.py. Run with:

    streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import streamlit as st

from control_tower.audit.trail import get_trail
from control_tower.db.models import (
    Approval,
    Case,
    DemandForecast,
    InventoryPosition,
    ManufacturingOrder,
    Product,
    PurchaseOrder,
    Shipment,
    Site,
    Supplier,
)
from control_tower.db.session import get_session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATA_DIR = PROJECT_ROOT / "test data"

# CSV filename stem -> (model, date columns, bool columns). Parent tables
# first so inserts respect foreign keys; reversed order is used on delete.
TABLE_SPECS = [
    ("sites", Site, [], []),
    ("suppliers", Supplier, [], []),
    ("products", Product, [], ["is_critical"]),
    ("inventory_positions", InventoryPosition, ["as_of_date"], []),
    ("demand_forecast", DemandForecast, ["period"], []),
    ("purchase_orders", PurchaseOrder, ["promised_date", "expected_date"], []),
    ("manufacturing_orders", ManufacturingOrder, ["planned_completion_date"], []),
    ("shipments", Shipment, ["eta"], []),
]

STATUS_COLORS = {
    "OPEN": "#D32F2F",
    "INVESTIGATING": "#D32F2F",
    "PENDING_APPROVAL": "#D32F2F",
    "APPROVED": "#8A8A8A",
    "REJECTED": "#8A8A8A",
    "EXECUTING": "#8A8A8A",
    "CLOSED": "#4F4F4F",
}


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#8A8A8A")
    return (
        f'<span style="background-color:{color};color:white;padding:2px 10px;'
        f'border-radius:10px;font-size:0.85em;">{status}</span>'
    )


def load_uploaded_files(uploaded_files) -> list[str]:
    """Replace the matching table(s) with the contents of the uploaded CSVs.
    Filenames must match a TABLE_SPECS stem, e.g. `products.csv`."""
    by_stem = {Path(f.name).stem.lower(): f for f in uploaded_files}
    known_stems = {stem for stem, *_ in TABLE_SPECS}
    unmatched = [f.name for f in uploaded_files if Path(f.name).stem.lower() not in known_stems]
    messages = []
    with get_session() as session:
        for stem, model, _, _ in reversed(TABLE_SPECS):
            if stem in by_stem:
                session.query(model).delete()
        for stem, model, date_cols, bool_cols in TABLE_SPECS:
            if stem not in by_stem:
                continue
            df = pd.read_csv(by_stem[stem])
            for col in date_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col]).dt.date
            for col in bool_cols:
                if col in df.columns:
                    df[col] = df[col].astype(bool)
            records = df.where(pd.notnull(df), None).to_dict("records")
            session.add_all(model(**r) for r in records)
            messages.append(f"{stem}: loaded {len(records)} rows")
    if unmatched:
        messages.append(f"ignored (no matching table): {', '.join(unmatched)}")
    return messages


@st.cache_data(ttl=5)
def load_data():
    with get_session() as session:
        products = {p.product_id: p.name for p in session.query(Product).all()}
        sites = {s.site_id: s.name for s in session.query(Site).all()}
        cases = [
            {
                "case_id": c.case_id,
                "product_id": c.product_id,
                "product_name": products.get(c.product_id, c.product_id),
                "site_id": c.site_id,
                "site_name": sites.get(c.site_id, c.site_id),
                "status": c.status,
                "risk_score": c.risk_score,
                "days_of_supply": c.days_of_supply,
                "detected_at": c.detected_at.isoformat() if c.detected_at else None,
                "closed_at": c.closed_at.isoformat() if c.closed_at else None,
                "findings_json": c.findings_json,
                "scenarios_json": c.scenarios_json,
                "recommended_action_json": c.recommended_action_json,
            }
            for c in session.query(Case).order_by(Case.detected_at.desc()).all()
        ]
        approvals = [
            {
                "approval_id": a.approval_id,
                "case_id": a.case_id,
                "recommended_action_json": a.recommended_action_json,
                "status": a.status,
                "requested_at": a.requested_at.isoformat() if a.requested_at else None,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                "decided_by": a.decided_by,
                "decision_note": a.decision_note,
            }
            for a in session.query(Approval).all()
        ]
    return cases, approvals


st.set_page_config(page_title="Pharma Supply Chain Control Tower", layout="wide")

cases, approvals = load_data()

header_col, refresh_col = st.columns([6, 1])
with header_col:
    st.title("Pharma Supply Chain Control Tower")
    st.caption("Phase 1 — Stockout Vertical Slice")
with refresh_col:
    if st.button("Refresh", width="stretch"):
        load_data.clear()
        st.rerun()

active = [c for c in cases if c["status"] not in ("CLOSED", "REJECTED")]
pending = [c for c in cases if c["status"] == "PENDING_APPROVAL"]
closed = [c for c in cases if c["status"] == "CLOSED"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total cases", len(cases))
m2.metric("Active", len(active))
m3.metric("Pending approval", len(pending))
m4.metric("Closed", len(closed))

st.divider()
with st.expander("Data management", expanded=False):
    st.markdown(
        "Sample CSVs (from `python scripts/generate_synthetic_data.py`) are in "
        f"`{TEST_DATA_DIR.name}/`. Upload one or more CSVs named after a table "
        "(`products.csv`, `sites.csv`, `suppliers.csv`, `inventory_positions.csv`, "
        "`demand_forecast.csv`, `purchase_orders.csv`, `manufacturing_orders.csv`, "
        "`shipments.csv`) to **replace** that table's rows."
    )
    uploaded = st.file_uploader("Upload CSV file(s)", type="csv", accept_multiple_files=True)
    if uploaded and st.button("Load uploaded files into database"):
        try:
            messages = load_uploaded_files(uploaded)
            st.session_state["upload_result"] = ("success", "Loaded — " + "; ".join(messages))
        except Exception as exc:
            st.session_state["upload_result"] = ("error", f"Failed to load data: {exc}")
        load_data.clear()
        st.rerun()
    if "upload_result" in st.session_state:
        kind, msg = st.session_state["upload_result"]
        if kind == "success":
            st.success(msg)
        else:
            st.error(msg)

    st.markdown("Detect stockout risk on the current data, investigate, and request approval "
                "(`scripts/run_detection.py`). The investigation step calls the configured "
                "Anthropic credentials in this environment.")
    if st.button("Run detection now"):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "run_detection.py")],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        st.session_state["detection_output"] = (result.stdout or "") + (result.stderr or "")
        load_data.clear()
        st.rerun()
    if "detection_output" in st.session_state:
        st.code(st.session_state["detection_output"], language="text")

st.divider()
with st.container(border=True):
    st.markdown("### 🧪 Agent Test Bench — Manufacturing Agent _(Phase 2, in progress)_")
    st.caption(
        "Manually runs the newly built Manufacturing Agent standalone against a product's "
        "manufacturing orders — outside the full detect → investigate → decide pipeline, and "
        "not tied to a real case. For trying out the agent in isolation while Phase 2 is being built."
    )
    with get_session() as session:
        test_products = [(p.product_id, p.name) for p in session.query(Product).order_by(Product.product_id).all()]
    if not test_products:
        st.info("No products loaded yet — upload `products.csv` above first.")
    else:
        test_product_id = st.selectbox(
            "Product", [pid for pid, _ in test_products],
            format_func=lambda pid: f"{pid} — {dict(test_products)[pid]}",
            key="mfg_test_product",
        )
        if st.button("Run Manufacturing Agent", key="run_mfg_agent"):
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "test_manufacturing_agent.py"), test_product_id],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            )
            st.session_state["mfg_test_output"] = (result.stdout or "") + (result.stderr or "")
        if "mfg_test_output" in st.session_state:
            st.code(st.session_state["mfg_test_output"], language="json")

st.subheader("Cases")

if not cases:
    st.info("No cases yet. Run `python scripts/run_detection.py` to generate one.")
else:
    cases_df = pd.DataFrame(cases)[
        [
            "case_id", "product_name", "site_name", "status",
            "risk_score", "days_of_supply", "detected_at", "closed_at",
        ]
    ]
    st.dataframe(cases_df, width="stretch", hide_index=True)

    st.subheader("Case detail")
    case_id = st.selectbox("Select a case", [c["case_id"] for c in cases])
    case = next(c for c in cases if c["case_id"] == case_id)

    st.markdown(
        f"{status_badge(case['status'])} &nbsp;&nbsp; "
        f"**Risk score:** {case['risk_score']:.2f} &nbsp;&nbsp; "
        f"**Days of supply:** {case['days_of_supply']:.1f} &nbsp;&nbsp; "
        f"**Detected:** {case['detected_at']}",
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Findings**")
        if case["findings_json"]:
            st.json(json.loads(case["findings_json"]))
        else:
            st.write("None yet.")

        st.markdown("**Scenarios**")
        if case["scenarios_json"]:
            st.json(json.loads(case["scenarios_json"]))
        else:
            st.write("None yet.")

    with right:
        st.markdown("**Recommended action**")
        if case["recommended_action_json"]:
            st.json(json.loads(case["recommended_action_json"]))
        else:
            st.write("None yet.")

        st.markdown("**Approval**")
        case_approvals = [a for a in approvals if a["case_id"] == case_id]
        if case_approvals:
            st.dataframe(pd.DataFrame(case_approvals), width="stretch", hide_index=True)
        else:
            st.write("No approval requested yet.")

    approval_output_key = f"approval_output_{case_id}"

    pending_approval = next(
        (a for a in approvals if a["case_id"] == case_id and a["status"] == "PENDING"), None
    )
    if pending_approval:
        with st.container(border=True):
            st.markdown("**Human approval required**")
            st.json(json.loads(pending_approval["recommended_action_json"]))
            decided_by = st.text_input(
                "Decided by", value="dashboard-user", key=f"decided_by_{case_id}"
            )
            note = st.text_input("Note (optional)", key=f"note_{case_id}")
            approve_col, reject_col = st.columns(2)
            decision = None
            with approve_col:
                if st.button("Approve", type="primary", width="stretch", key=f"approve_{case_id}"):
                    decision = "--approve"
            with reject_col:
                if st.button("Reject", width="stretch", key=f"reject_{case_id}"):
                    decision = "--reject"
            if decision:
                cmd = [
                    sys.executable, str(PROJECT_ROOT / "scripts" / "approve.py"),
                    case_id, decision, "--decided-by", decided_by or "dashboard-user",
                ]
                if note:
                    cmd += ["--note", note]
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
                st.session_state[approval_output_key] = (result.stdout or "") + (result.stderr or "")
                load_data.clear()
                st.rerun()
    if approval_output_key in st.session_state:
        st.markdown("**Last approval action result**")
        st.code(st.session_state[approval_output_key], language="text")

    st.markdown("**Audit trail**")
    with get_session() as session:
        trail = get_trail(session, case_id)
    if trail:
        trail_df = pd.DataFrame(trail)[["timestamp", "actor", "action", "outcome", "payload"]]
        trail_df["payload"] = trail_df["payload"].apply(lambda p: json.dumps(p, default=str))
        st.dataframe(trail_df, width="stretch", hide_index=True)
    else:
        st.write("No audit events yet.")
