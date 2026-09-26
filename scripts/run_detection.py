#!/usr/bin/env python3
"""CLI: scan for stockout risk, investigate, and request approval.

    python scripts/run_detection.py

Detection itself (risk_detector.detect_stockout_risks) is deterministic and
touches the control tower's own case table directly, per the same pattern
used by guardrails/policy.py. Everything after that - the Demand/Inventory/
Supply/Decision agents - reasons over real enterprise data only through
MCP tools, spawned here as real subprocesses via StdioToolDispatcher.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from control_tower.agents.base import StdioToolDispatcher
from control_tower.db.session import get_session
from control_tower.domain.risk_detector import detect_stockout_risks
from control_tower.orchestrator import run_orchestration


async def _main() -> None:
    with get_session() as session:
        new_cases = detect_stockout_risks(session, today=date.today())
        case_ids = [c.case_id for c in new_cases]

    if not case_ids:
        print("No new stockout risks detected.")
        return

    async with StdioToolDispatcher() as dispatcher:
        for case_id in case_ids:
            print(f"\n=== Case {case_id}: investigating ===")
            result = await run_orchestration(dispatcher, case_id)

            print("Findings:")
            for role, finding in result["findings"].items():
                marker = "x" if finding.get("contributes") else " "
                print(f"  [{marker}] {role:<9} {finding.get('cause_category')}: {finding.get('evidence')}")

            print("Candidate options:")
            for opt in result["candidate_options"]:
                print(f"  - {opt['action_type']}: {opt['params']}")

            decision = result["decision"]
            approval_id = decision.get("approval_id")
            if approval_id:
                print(f"Recommendation: {decision.get('recommended_action_type')} {decision.get('recommended_params')}")
                print(f"Awaiting human approval: python scripts/approve.py {case_id} --approve")
                print(f"  (approval_id={approval_id})")
            else:
                print(f"No approval request created - {decision.get('rationale')}")


if __name__ == "__main__":
    asyncio.run(_main())
