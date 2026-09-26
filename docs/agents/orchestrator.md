# Orchestrator

**Not an LLM agent.** Deterministic coordinator (`src/control_tower/orchestrator.py`),
documented here because CLAUDE.md's architecture diagram names it as a
layer. Per Principle 3 ("deterministic logic stays outside the LLM") and
the Do-Not rule against creating an agent where a deterministic service is
sufficient, sequencing sub-agents and tracking case state needs no
reasoning.

- **Purpose**: sequence the Demand, Inventory, and Supply investigation
  agents against an `OPEN` case, build the candidate mitigation options the
  Decision Agent may choose among, hand off to the Decision Agent, and
  narrate progress to the audit trail.
- **Responsibilities**: flip `Case.status` to `INVESTIGATING`; run the three
  investigation agents; deterministically compute candidate options
  (`_candidate_options`) from real open POs / suppliers / demand data;
  persist `Case.findings_json`; invoke the Decision Agent; write
  `investigation_started` / `investigation_completed` / `decision_recorded`
  audit events.
- **Inputs**: `case_id` (must reference an existing `Case`), a `ToolDispatcher`.
- **Outputs**: `{case_id, findings, candidate_options, decision}` dict.
  Leaves the case in `PENDING_APPROVAL` (or unchanged if the Decision
  Agent's recommendation was denied by Gate A).
- **Sub-agents**: Demand Agent, Inventory Agent, Supply Agent (investigation,
  run sequentially), Decision Agent (scenario generation).
- **Tools**: none directly - it accesses the control tower's own
  `cases`/`purchase_orders`/`inventory_positions`/`suppliers` tables
  directly via SQLAlchemy, the same pattern already used by
  `risk_detector.py` and `guardrails/policy.py` (deterministic
  infrastructure, not an LLM reasoning component, so CLAUDE.md's "no direct
  DB access" rule for *agents* doesn't apply here).
- **MCP dependencies**: none directly; the agents it calls depend on
  `inventory_mcp`, `supplier_mcp`, `workflow_audit_mcp`.
- **Guardrails**: none of its own - Gate A runs inside
  `create_approval_request`, called by the Decision Agent it invokes.
- **Hooks**: none (see Phase 1 architecture doc - hooks were folded into
  guardrail gates and `record_event()` for this slice).
- **Skills**: none.
- **Human approval requirements**: none itself; it is what produces the
  case that a human later approves or rejects via `scripts/approve.py`.
- **Failure handling**: raises `ValueError` if `case_id` is unknown. Any
  exception from a sub-agent propagates uncaught - there's no partial-retry
  logic in this slice; a case that fails mid-investigation is left in
  `INVESTIGATING` for a human/operator to re-run or inspect.
- **Audit requirements**: writes `investigation_started`,
  `investigation_completed`, `decision_recorded` narrative events directly
  via `audit/trail.record_event()`. Every MCP tool call made by the
  sub-agents it invokes writes its own event too.
- **Evaluation criteria**: given a case with real findings, produces a
  `PENDING_APPROVAL` case with a non-empty, real-data-backed candidate
  option list and a decision referencing one of those options. Covered by
  `tests/test_orchestrator.py` and `tests/test_e2e_scenario.py`.
