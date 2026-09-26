#!/usr/bin/env python3
"""CLI: run the Manufacturing Agent standalone against a product, outside
the full detect -> investigate -> decide pipeline. For manually testing
the agent (e.g. from the dashboard's "Agent Test Bench" section) against
whatever manufacturing_orders rows exist for a product.

    python scripts/test_manufacturing_agent.py <product_id>

Not tied to a real case - passes a synthetic case_id so the tool's audit
event is clearly distinguishable from a real investigation's trail
(case_id is nullable/unvalidated on get_manufacturing_status, so this is
safe: see docs/mcp/manufacturing.md).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from control_tower.agents.base import StdioToolDispatcher
from control_tower.agents.manufacturing_agent import run_manufacturing_agent


async def _main(product_id: str) -> None:
    case_id = f"AGENT-TEST-{uuid4().hex[:8]}"
    async with StdioToolDispatcher() as dispatcher:
        finding = await run_manufacturing_agent(dispatcher, case_id, product_id)
    print(json.dumps({"product_id": product_id, "test_case_id": case_id, "finding": finding}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/test_manufacturing_agent.py <product_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
