# manufacturing_mcp

`src/control_tower/mcp_servers/manufacturing_server.py` — run standalone
with `python -m control_tower.mcp_servers.manufacturing_server`.

One read tool today (used by the Manufacturing Agent); the intended home
for the tools the later Phase 2 agents (Capacity, Material Availability,
Scheduling) will need, rather than scattering manufacturing-domain tools
across other servers.

Moved out of `supplier_mcp` when the Manufacturing Agent was introduced -
see `docs/architecture/phase2-manufacturing-agent.md`.

## `get_manufacturing_status`

- **Purpose**: return in-flight manufacturing orders for a product.
- **Input**: `{product_id: str, case_id: str | None}`.
- **Output**: `list[ManufacturingOrderOut{mo_id, product_id, site_id, planned_qty, status, planned_completion_date}]`
  (empty list if none, not an error).
- **Authorization**: none beyond allow-listing.
- **Validation**: none.
- **Error handling**: none.
- **Audit behavior**: every call writes a `record_event` row.
- **Idempotency**: pure read.
