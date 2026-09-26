# Phase 1 Guardrails

`src/control_tower/guardrails/policy.py`

CLAUDE.md is explicit that security, authorization, and compliance checks
must never rely solely on LLM instructions — they must be enforceable at
runtime, independent of what any agent's system prompt says or what the
model decides to do. This module is the concrete implementation of that
rule for Phase 1: two deterministic gates, called *inside* the MCP tool
handlers that would otherwise mutate state, not from orchestration code an
agent could bypass by reasoning around it. Every check fails closed — on
any doubt, ambiguity, or missing data, `allowed=False`.

Both gates return a `GuardrailResult{allowed, gate, reason}` rather than
raising directly, so the calling tool handler controls exactly what gets
audited and how the denial is surfaced to the model.

## Gate A — `gate_a_pre_approval`

**Enforcement point**: called inside `create_approval_request`
(`workflow_audit_mcp`), *before* any `Approval` row is written or
`Case.status` changed. This is what actually decides whether a human is
ever asked, regardless of what the Decision Agent recommended.

**Checks, in order (fail-closed at the first failure)**:
1. `case_id` must reference a real `Case`.
2. `Case.status` must not already be in
   `{PENDING_APPROVAL, APPROVED, EXECUTING, CLOSED}` — prevents a second,
   concurrent approval request for a case that already has one in flight
   or has already been resolved.
3. `action_type` must be in `config.ALLOWED_MITIGATION_ACTIONS`
   (`{expedite_shipment, emergency_po}` for this slice — `stock_reallocation`
   was deliberately excluded; see `docs/architecture/phase1-stockout-slice.md`).
4. Action-specific parameter validation:
   - `emergency_po`: `qty` must be a positive number not exceeding
     `config.MAX_EMERGENCY_PO_QTY`, and `supplier_id` must be present.
   - `expedite_shipment`: `po_id` must be present and must reference a
     real `PurchaseOrder` that belongs to *this case's* `product_id`
     (prevents expediting an unrelated product's PO by mistake or by
     prompt injection via tool arguments).

**On denial**: the tool handler records a `DENIED` audit event with the
gate's `reason` and raises `ToolError` — no `Approval` row and no
`Case.status` change occur. The Decision Agent's system prompt requires it
to report the denial in its final answer rather than retry with a
different action.

## Gate B — `gate_b_pre_execution`

**Enforcement point**: called inside both `create_expedite_shipment` and
`create_emergency_po` (`supplier_mcp`), *before* any PO/shipment state is
mutated. This is the re-validation immediately before execution — it does
not trust that the approval used to request execution is still valid,
current, or unmodified.

**Checks, in order (fail-closed at the first failure)**:
1. `approval_id` must reference a real `Approval`.
2. `Approval.status` must be exactly `APPROVED` (not `PENDING`, not
   `REJECTED`, and critically not already consumed — see idempotency
   below).
3. The approval must not be older than `config.APPROVAL_EXPIRY_HOURS` —
   a stale approval cannot be executed even if never explicitly rejected.
4. The `action_type`/`params` being executed must exactly match the
   `recommended_action_json` stored on the approval at request time — any
   mismatch is treated as possible tampering and denied, regardless of
   source (a compromised agent, a hand-crafted tool call, or a bug).
5. The approval's `Case` must exist and be in `APPROVED` status — not
   already `EXECUTING` or `CLOSED`.

**Idempotency (the key property)**: on success, Gate B *atomically flips
`Case.status` to `EXECUTING`* within the same DB session/transaction
before returning `allowed=True`. This means a second execution attempt
against the same approval — whether from a retried CLI call, a duplicated
tool call, or a re-run script — fails check 5 (case is no longer
`APPROVED`) and is denied. The idempotency guarantee lives in this state
transition, not in caller discipline or request deduplication.

**On denial**: the tool handler records a `DENIED` audit event with the
reason and raises `ToolError` — no PO/shipment/supplier mutation occurs.
The Execution Agent's system prompt requires it to report `executed: false`
and the reason, and explicitly forbids calling `close_case` in that case.

## Why these two gates, not more

Two gates map exactly to the two points in the flow where trust changes
hands: Gate A is where an *agent's recommendation* becomes a *human-facing
request*, and Gate B is where a *human's decision* becomes an *actual
mutation of enterprise state*. Every other tool in the system is either
pure-read (no gate needed) or the terminal `close_case`/`resolve_approval`
steps, which are guarded by their own inline state checks
(`case.status != "EXECUTING"`, `approval.status != "PENDING"`) rather than
a named gate, since they don't authorize a *new* action — they finalize
one already gated upstream.

## Testing

Gate A is exercised directly (via `create_approval_request`) in
`tests/test_mcp_workflow_audit.py` (e.g.
`test_create_approval_request_denied_bad_action_type`,
`test_create_approval_request_denied_duplicate_in_flight`). Gate B is
exercised directly (via the execution tools) in
`tests/test_mcp_supplier.py`. Every agent/orchestrator/e2e test that
exercises approval or execution implicitly re-verifies both gates
end-to-end: `tests/test_agents_decision_execution.py`,
`tests/test_orchestrator.py`, `tests/test_e2e_scenario.py` (including the
idempotency re-run assertions: a second `resolve_approval` and a second
`create_expedite_shipment` on the same case both raise `MCPToolError`
without changing final state).
