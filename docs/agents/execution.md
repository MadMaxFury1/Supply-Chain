# Execution Agent

`src/control_tower/agents/execution_agent.py`

- **Purpose**: carry out a human-approved mitigation action, verify it
  took effect, and close the case.
- **Responsibilities**: call the one write tool matching the approved
  `action_type` (`create_expedite_shipment` or `create_emergency_po`);
  re-read the resulting state via a read tool to verify it; call
  `close_case`; if the approval is not actually `APPROVED` (or has already
  been executed), report the denial rather than retry with a different
  action.
- **Inputs**: `case_id`, `approval_id`, `action_type`, `params`,
  `product_id`, `site_id`.
- **Outputs**: `{executed: bool, execution_detail, verified: bool, verification_detail, case_closed: bool}`.
- **Sub-agents**: none.
- **Tools**: `create_expedite_shipment`, `create_emergency_po` (writes, on
  `supplier_mcp`); `get_inventory_position`, `get_open_purchase_orders`
  (reads, for verification, on `inventory_mcp`); `close_case` (write, on
  `workflow_audit_mcp`).
- **MCP dependencies**: `supplier_mcp`, `inventory_mcp`, `workflow_audit_mcp`.
- **Guardrails**: **Gate B** (`gate_b_pre_execution`) runs *inside* each
  write tool before anything executes - re-validates the approval is
  `APPROVED`, not already executed/expired, and that the action/params
  being executed exactly match what was approved. This is the fail-closed
  check that prevents a tampered or stale approval from being acted on;
  the agent cannot bypass it, only receive a denial and report it.
- **Hooks**: none of its own; `hooks.on_case_closed` fires inside
  `close_case` (the tool this agent calls), not inside this agent's code.
- **Skills**: none.
- **Human approval requirements**: this agent only ever runs after a human
  has already approved via `scripts/approve.py` - invoked either directly
  from the CLI or via the dashboard's Approve/Reject buttons
  (`dashboard/app.py`), which shell out to the same script; it never
  proceeds on a `PENDING` or `REJECTED` approval (Gate B denies those
  cases).
- **Failure handling**: a Gate B denial surfaces as an `is_error` tool
  result; the agent's final answer must report `executed: false` and
  explain why, and it must not call `close_case` in that case. Idempotency:
  a second execution attempt against an already-executed approval is
  denied by Gate B (the approval/PO state machine guards this), so
  re-running `approve.py` never double-executes.
- **Audit requirements**: every write and read tool call audits itself;
  `close_case` writes the final `case_closed` event, giving a complete,
  independently-verifiable trail from `investigation_started` through
  `case_closed`.
- **Evaluation criteria**: given a real `APPROVED` approval, executes the
  matching write tool, verifies via a read tool, and closes the case
  (`Case.status == "CLOSED"`, e.g. `PurchaseOrder.status == "EXPEDITED"`).
  Given a `PENDING` (not yet approved) approval, Gate B denies execution
  and case/PO state is unchanged. Covered by
  `tests/test_agents_decision_execution.py` and
  `tests/test_e2e_scenario.py` (including a repeat-call idempotency check).
