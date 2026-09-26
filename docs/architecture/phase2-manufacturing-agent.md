# Phase 2 — Manufacturing Agent: scope change note

Documented per CLAUDE.md's Do-Not rule against silent architecture
changes, same precedent as `docs/architecture/phase1-stockout-slice.md`.

## What changed

Phase 2 adds a dedicated **Manufacturing Agent**
(`agents/manufacturing_agent.py`) that investigates delayed manufacturing
orders, backed by a new **manufacturing_mcp** server
(`mcp_servers/manufacturing_server.py`) exposing `get_manufacturing_status`.

That tool previously lived on `supplier_mcp` and was used by the **Supply
Agent** as a secondary signal alongside supplier reliability. Adding a new,
separate Manufacturing Agent that also investigated manufacturing-order
delays would have duplicated the Supply Agent's existing responsibility —
CLAUDE.md's Do-Not rule explicitly forbids duplicating agents or MCP
tools. So this change **narrows the Supply Agent's scope** to supplier
reliability only, and moves manufacturing-order investigation to the new
agent, rather than additively creating an overlapping capability.

## Why a new MCP server instead of just sharing supplier_mcp

`manufacturing_mcp` is deliberately its own server rather than granting
the Manufacturing Agent access to `supplier_mcp`. It satisfies
`BUILD_PLAN.md`'s Phase 2 "Manufacturing MCP" item, and gives the three
subsequent Phase 2 agents (Capacity, Material Availability, Scheduling) —
which will need genuinely new manufacturing-domain tools not present in
any existing server — a natural home, rather than retrofitting a server
boundary later.

## Files touched

- New: `mcp_servers/manufacturing_server.py`, `agents/manufacturing_agent.py`
- Narrowed: `agents/supply_agent.py` (drops `get_manufacturing_status`),
  `mcp_servers/supplier_server.py` (drops `get_manufacturing_status` /
  `ManufacturingOrderOut`)
- Wired in: `orchestrator.py` (4th investigation call + `findings["manufacturing"]`),
  `agents/base.py` (new `"manufacturing"` server key), `agents/decision_agent.py`
  (system prompt wording)
- Docs updated: `docs/agents/supply.md`, `docs/mcp/supplier.md`; new
  `docs/agents/manufacturing.md`, `docs/mcp/manufacturing.md`
