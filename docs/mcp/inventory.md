# inventory_mcp

`src/control_tower/mcp_servers/inventory_server.py` — run standalone with
`python -m control_tower.mcp_servers.inventory_server`.

Read-only. No write tools live on this server at all (least privilege: an
agent scoped to `inventory_mcp` cannot mutate any enterprise state, by
construction, not by convention).

## `get_inventory_position`

- **Purpose**: return the latest on-hand / safety-stock position for a
  product at a site.
- **Input**: `{product_id: str, site_id: str, case_id: str | None}`.
- **Output**: `InventoryPositionOut{product_id, site_id, on_hand_qty, safety_stock_qty, unit_of_measure, as_of_date}`.
- **Authorization**: none beyond MCP allow-listing (read-only, no
  guardrail needed).
- **Validation**: none beyond existence — no position found → error.
- **Error handling**: raises `ToolError` if no position row exists for the
  `(product_id, site_id)` pair; audited as `ERROR` before raising.
- **Audit behavior**: every call (success or not-found) writes a
  `record_event` row via `audit/trail.py`.
- **Idempotency**: pure read, trivially idempotent.

## `list_inventory_positions`

- **Purpose**: return the latest on-hand / safety-stock position at every
  site for a product, optionally excluding one site. Used by the
  Reallocation Scout sub-agent (`docs/agents/reallocation-scout.md`) to
  check for surplus stock at sites other than a case's deficit site.
- **Input**: `{product_id: str, exclude_site_id: str | None, case_id: str | None}`.
- **Output**: `list[InventoryPositionOut{product_id, site_id, on_hand_qty, safety_stock_qty, unit_of_measure, as_of_date}]`
  (empty list if none - not an error, same convention as
  `get_open_purchase_orders`).
- **Authorization**: none beyond MCP allow-listing (read-only, no guardrail
  needed).
- **Validation**: none.
- **Error handling**: none - always succeeds, possibly with an empty list.
- **Audit behavior**: every call writes a `record_event` row (`SUCCESS`).
- **Idempotency**: pure read.

## `get_demand_forecast`

- **Purpose**: return up to `months` of forecast-vs-actual demand history
  for a product/site, oldest-first.
- **Input**: `{product_id: str, site_id: str, months: int = 6, case_id: str | None}`.
- **Output**: `list[DemandForecastPoint{period, forecast_qty, actual_qty}]`.
- **Authorization**: none beyond allow-listing.
- **Validation**: none beyond existence — no rows found → error.
- **Error handling**: raises `ToolError` if no demand history exists;
  audited as `ERROR` before raising.
- **Audit behavior**: every call writes a `record_event` row.
- **Idempotency**: pure read.

## `get_open_purchase_orders`

- **Purpose**: return open or delayed purchase orders for a product.
- **Input**: `{product_id: str, case_id: str | None}`.
- **Output**: `list[PurchaseOrderOut{po_id, product_id, supplier_id, qty, status, promised_date, expected_date}]`
  (empty list if none — not an error, since "no open POs" is itself a
  meaningful finding for the Inventory Agent).
- **Authorization**: none beyond allow-listing.
- **Validation**: none.
- **Error handling**: none — always succeeds, possibly with an empty list.
- **Audit behavior**: every call writes a `record_event` row (`SUCCESS`).
- **Idempotency**: pure read.

Note on MCP wire shape: `get_open_purchase_orders` returns a bare list,
which the MCP protocol wraps as `{"result": [...]}` in
`structured_content` (structured content must be a JSON object); the
harness in `agents/base.py` (`_unwrap_call_result`) detects and unwraps
this so agents see a plain list.
