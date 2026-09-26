# supplier_mcp

`src/control_tower/mcp_servers/supplier_server.py` — run standalone with
`python -m control_tower.mcp_servers.supplier_server`.

One read tool (used by the Supply Agent) plus the **only two
write/execution tools in the entire system** — `create_expedite_shipment`
and `create_emergency_po`. These are the sole capability boundary the
Execution Agent can act through; no other tool anywhere can mutate
purchase order, shipment, or supplier state.

`get_manufacturing_status` used to live here too; it moved to the new
`manufacturing_mcp` (`docs/mcp/manufacturing.md`) when the Manufacturing
Agent was introduced in Phase 2 - see
`docs/architecture/phase2-manufacturing-agent.md`.

## `get_supplier_status`

- **Purpose**: return reliability/profile info for a supplier.
- **Input**: `{supplier_id: str, case_id: str | None}`.
- **Output**: `SupplierStatusOut{supplier_id, name, reliability_score, country}`.
- **Authorization**: none beyond allow-listing (read-only).
- **Validation**: `supplier_id` must exist.
- **Error handling**: raises `ToolError` if unknown, audited as `ERROR`
  first.
- **Audit behavior**: every call writes a `record_event` row.
- **Idempotency**: pure read.

## `create_expedite_shipment` (write / execution)

- **Purpose**: execute an approved `expedite_shipment` mitigation — mark a
  PO (and its shipment, if any) as expedited with a pulled-forward ETA
  (`today + 3 days`).
- **Input**: `{approval_id: str, po_id: str, case_id: str}`.
- **Output**: `ExecutionResult{approval_id, action_type, status: "EXECUTED"|"DENIED", detail, reference_id}`.
- **Authorization**: **Guardrail Gate B** (`gate_b_pre_execution`), called
  *inside this handler* before any mutation — this is the actual
  enforcement point, not a caller-side check the Execution Agent could
  skip. Verifies the approval exists, is `APPROVED`, has not already been
  executed, and that `po_id` exactly matches what was approved.
- **Validation**: `po_id` must reference a real `PurchaseOrder`.
- **Error handling**: on Gate B denial or unknown `po_id`, writes a
  `DENIED`/`ERROR` audit event and raises `ToolError` — no partial
  mutation occurs (the whole handler runs inside one DB session/transaction).
- **Audit behavior**: writes a `SUCCESS` event with `approval_id`, `po_id`,
  and the new ETA on success; a `DENIED` event with the reason on failure.
- **Idempotency**: **not** independently idempotent by `po_id` — idempotency
  is enforced upstream by Gate B via the approval's state machine (an
  approval can only be executed once; see `resolve_approval`'s docstring
  and `guardrails/policy.py`). A second call with the same `approval_id`
  is denied.

## `create_emergency_po` (write / execution)

- **Purpose**: execute an approved `emergency_po` mitigation — raise a new
  purchase order against an (alternate) supplier.
- **Input**: `{approval_id: str, supplier_id: str, qty: float, case_id: str}`.
- **Output**: `ExecutionResult{approval_id, action_type, status: "EXECUTED"|"DENIED", detail, reference_id}`
  where `reference_id` is the newly created `po_id` (`PO-EMG-XXXXXX`).
- **Authorization**: **Guardrail Gate B**, called inside this handler,
  same as above — verifies approval is `APPROVED`, not already executed,
  and `supplier_id`/`qty` match what was approved.
- **Validation**: `supplier_id` must reference a real `Supplier`;
  `case.product_id` is used for the new PO (so the PO is always for the
  product the case is actually about, not whatever the caller passes).
- **Error handling**: on Gate B denial or unknown `supplier_id`, writes a
  `DENIED`/`ERROR` audit event and raises `ToolError`.
- **Audit behavior**: writes a `SUCCESS` event with `approval_id`,
  generated `po_id`, `supplier_id`, `qty` on success; `DENIED` with reason
  on failure.
- **Idempotency**: same as `create_expedite_shipment` — enforced via the
  approval state machine in Gate B, not by request deduplication. A second
  call with the same `approval_id` is denied and does not raise a second PO.
