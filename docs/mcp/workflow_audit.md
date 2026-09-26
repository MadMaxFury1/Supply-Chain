# workflow_audit_mcp

`src/control_tower/mcp_servers/workflow_audit_server.py` — run standalone
with `python -m control_tower.mcp_servers.workflow_audit_server`.

The approval queue (the human-in-the-loop boundary) and the single sink
every case's audit trail is written to and read from.

## `create_approval_request` (write)

- **Purpose**: request human approval for a recommended mitigation.
- **Input**: `{case_id: str, action_type: str, params: dict, summary: str, scenarios: list[dict] | None}`.
- **Output**: `ApprovalOut{approval_id, case_id, action_type, params, status, requested_at, decided_at, decided_by, decision_note}`.
- **Authorization**: **Guardrail Gate A** (`gate_a_pre_approval`), called
  *inside this handler* before anything is written — the Decision Agent
  only *recommends*; this tool decides whether a human is even asked.
  Checks: no approval already in flight for this case, `action_type` is in
  `config.ALLOWED_MITIGATION_ACTIONS`, and `params` are valid/reference
  real entities belonging to this case's product.
- **Validation**: as above, entirely inside Gate A.
- **Error handling**: on Gate A denial, writes a `DENIED` audit event and
  raises `ToolError` — no `Approval` row and no `Case.status` change occur
  (fail-closed: nothing is written on denial).
- **Audit behavior**: `SUCCESS` event with `approval_id`/`action_type`/`params`/`summary`
  on success; `DENIED` with the gate's reason on failure. Also flips
  `Case.status` to `PENDING_APPROVAL` and stores `recommended_action_json`
  / `scenarios_json` on the case.
- **Idempotency**: Gate A's "no approval already in flight" check prevents
  creating a second concurrent approval for the same case.

## `get_approval_status` (read)

- **Purpose**: look up an approval request by id.
- **Input**: `{approval_id: str}`.
- **Output**: `ApprovalOut` (see above).
- **Authorization**: none (read-only).
- **Validation**: `approval_id` must exist.
- **Error handling**: raises `ToolError` if unknown.
- **Audit behavior**: not audited (pure lookup, no state change).
- **Idempotency**: pure read.

## `resolve_approval` (write — the human decision point)

- **Purpose**: record a human's `APPROVED`/`REJECTED` decision on a
  pending approval. This is the human decision step, invoked via
  `scripts/approve.py` from the CLI or via the dashboard's Approve/Reject
  buttons (`dashboard/app.py`, which shells out to the same script) - both
  are thin entry points onto this one tool, so the guardrail/audit
  behavior below is identical regardless of which one is used.
- **Input**: `{approval_id: str, decision: "APPROVED"|"REJECTED", decided_by: str, note: str = ""}`.
- **Output**: `ApprovalOut`.
- **Authorization**: none beyond the state check below — the human
  decision itself *is* the authorization event; there's no further gate
  on top of it. (Gate B re-validates this decision again immediately
  before any execution tool acts on it — see `docs/mcp/supplier.md`.)
- **Validation**: `approval_id` must exist and currently be `PENDING`.
- **Error handling**: raises `ToolError` for an unknown `approval_id` or
  one that's already been decided — this is the primary idempotency
  guard for the whole approve→execute flow (documented explicitly in the
  function's own docstring: "prevents a repeated `approve` call from
  re-triggering execution").
- **Audit behavior**: `SUCCESS` event with the decision/decider/note; a
  `DENIED` event if the approval was already decided. Also sets
  `Case.status` to `APPROVED`/`REJECTED` (and `closed_at` immediately on
  `REJECTED`, since a rejected case needs no execution step).
- **Idempotency**: enforced via the `PENDING`-only state check — a second
  `resolve_approval` call on the same `approval_id` always fails, never
  re-applies a decision.

## `close_case` (write)

- **Purpose**: close a case once its approved action has been executed
  and verified.
- **Input**: `{case_id: str, verification: dict, actor: str = "execution_agent"}`.
- **Output**: `CaseOut{case_id, product_id, site_id, status, risk_score, days_of_supply, closed_at}`.
- **Authorization**: requires `Case.status == "EXECUTING"` — cannot close
  a case that hasn't gone through the execution step (or is already
  closed).
- **Validation**: `case_id` must exist.
- **Error handling**: raises `ToolError` for unknown `case_id` or wrong
  status.
- **Audit behavior**: writes the final `close_case` `SUCCESS` event
  carrying the verification payload — the last entry in a case's trail.
  Also fires the `hooks.on_case_closed` lifecycle hook (logged
  notification; deterministic and fail-safe, never blocks closing).
- **Idempotency**: the `EXECUTING`-only check means a second `close_case`
  call (on an already-`CLOSED` case) is rejected rather than re-closing.

## `write_audit_event` (write)

- **Purpose**: write a narrative audit event not tied to a specific domain
  tool call (e.g. `investigation_started`, `decision_recorded` — used by
  the deterministic orchestrator).
- **Input**: `{case_id: str | None, actor: str, action: str, payload: dict, outcome: str = "SUCCESS"}`.
- **Output**: `AuditEventOut{event_id, case_id, actor, action, payload, outcome, timestamp}`.
- **Authorization**: none — this is the generic audit sink, callable by
  any actor to record any narrative event.
- **Validation**: none.
- **Error handling**: none — always succeeds.
- **Audit behavior**: is itself the audit write.
- **Idempotency**: N/A — append-only, each call is a distinct event by
  design.

## `get_audit_trail` (read)

- **Purpose**: return the full ordered audit trail for a case.
- **Input**: `{case_id: str}`.
- **Output**: `list[AuditEventOut]`, chronological.
- **Authorization**: none (read-only).
- **Validation**: none — an unknown `case_id` simply returns an empty list.
- **Error handling**: none.
- **Audit behavior**: not audited itself (pure read).
- **Idempotency**: pure read.
