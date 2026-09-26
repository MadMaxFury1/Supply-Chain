"""Lifecycle hooks - CLAUDE.md: "Hooks must be deterministic, observable,
fail safe." These are plain functions fired at fixed points in the case
lifecycle (never LLM-driven); a hook failure is caught and logged rather
than allowed to break the pipeline that fired it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("control_tower.hooks")


def _run_safely(name: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception("hook %s failed - continuing", name)


def on_case_opened(case_id: str, product_id: str, site_id: str, risk_score: float) -> None:
    """Fires when risk_detector opens a new case."""
    _run_safely(
        "on_case_opened", logger.warning,
        "STOCKOUT RISK OPENED case=%s product=%s site=%s risk_score=%.2f",
        case_id, product_id, site_id, risk_score,
    )


def on_case_closed(case_id: str, status: str) -> None:
    """Fires when workflow_audit_mcp's close_case tool closes a case."""
    _run_safely("on_case_closed", logger.info, "CASE CLOSED case=%s status=%s", case_id, status)
