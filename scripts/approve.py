#!/usr/bin/env python3
"""CLI: the human-in-the-loop approval step. Resolves a pending approval,
then (if approved) runs the Execution agent to execute, verify, and close
the case.

    python scripts/approve.py CASE-XXXXXXXX --approve [--decided-by alice]
    python scripts/approve.py CASE-XXXXXXXX --reject --note "not needed"

Resolution is asynchronous by design: this is a separate CLI invocation
from `run_detection.py`, not a blocking prompt, so a human can review the
case at their own pace. Idempotency (a repeated `approve` call must not
re-execute) is enforced inside resolve_approval / Gate B, not here.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from control_tower.agents.base import StdioToolDispatcher
from control_tower.agents.execution_agent import run_execution_agent
from control_tower.db.models import Approval, Case
from control_tower.db.session import get_session


def _find_pending_approval(case_id: str) -> tuple[str, dict, str, str]:
    """Deterministic lookup of the case's most recent PENDING approval -
    not an agent's job, and not a write, so plain DB access here is fine."""
    with get_session() as session:
        case = session.get(Case, case_id)
        if case is None:
            raise SystemExit(f"no such case: {case_id}")
        approval = (
            session.query(Approval)
            .filter(Approval.case_id == case_id, Approval.status == "PENDING")
            .order_by(Approval.requested_at.desc())
            .first()
        )
        if approval is None:
            raise SystemExit(f"case {case_id} has no PENDING approval (status={case.status})")
        recommended = json.loads(approval.recommended_action_json)
        return approval.approval_id, recommended, case.product_id, case.site_id


async def _main(case_id: str, decision: str, decided_by: str, note: str) -> None:
    approval_id, recommended, product_id, site_id = _find_pending_approval(case_id)

    async with StdioToolDispatcher() as dispatcher:
        resolved = await dispatcher.call(
            "workflow_audit", "resolve_approval",
            {"approval_id": approval_id, "decision": decision, "decided_by": decided_by, "note": note},
        )
        print(f"Approval {approval_id} resolved: {resolved['status']} (by {decided_by})")

        if decision == "REJECTED":
            print("Case rejected; no execution performed.")
            return

        print("\nExecuting approved action...")
        result = await run_execution_agent(
            dispatcher,
            case_id=case_id,
            approval_id=approval_id,
            action_type=recommended["action_type"],
            params=recommended["params"],
            product_id=product_id,
            site_id=site_id,
        )
        print(json.dumps(result, indent=2))

        trail = await dispatcher.call("workflow_audit", "get_audit_trail", {"case_id": case_id})
        print("\nAudit trail:")
        for event in trail:
            print(f"  [{event['timestamp']}] {event['actor']:<16} {event['action']:<26} {event['outcome']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve or reject a pending mitigation for a stockout case.")
    parser.add_argument("case_id")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--reject", action="store_true")
    parser.add_argument("--decided-by", default="cli-user")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    decision = "APPROVED" if args.approve else "REJECTED"
    asyncio.run(_main(args.case_id, decision, args.decided_by, args.note))


if __name__ == "__main__":
    main()
