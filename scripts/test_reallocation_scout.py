#!/usr/bin/env python3
"""CLI: run the Reallocation Scout sub-agent standalone against a product and
deficit site, outside the full detect -> investigate -> decide pipeline. For
manually testing the sub-agent in isolation (mirrors
scripts/test_manufacturing_agent.py).

    python scripts/test_reallocation_scout.py <product_id> <deficit_site_id>

Not tied to a real case - passes a synthetic case_id, same convention as
test_manufacturing_agent.py.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from control_tower.agents.base import StdioToolDispatcher
from control_tower.agents.reallocation_scout_agent import run_reallocation_scout


async def _main(product_id: str, deficit_site_id: str) -> None:
    case_id = f"AGENT-TEST-{uuid4().hex[:8]}"
    async with StdioToolDispatcher() as dispatcher:
        finding = await run_reallocation_scout(dispatcher, case_id, product_id, deficit_site_id)
    print(json.dumps(
        {"product_id": product_id, "deficit_site_id": deficit_site_id, "test_case_id": case_id, "finding": finding},
        indent=2,
    ))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python scripts/test_reallocation_scout.py <product_id> <deficit_site_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
