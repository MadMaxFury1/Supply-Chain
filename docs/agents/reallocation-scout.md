# Reallocation Scout (sub-agent of the Inventory Agent)

`src/control_tower/agents/reallocation_scout_agent.py`

The first sub-agent in the codebase - every other agent spec lists
"Sub-agents: none." Introduced to fill a real gap without duplicating any
existing agent or tool (CLAUDE.md Do-Not): `config.py` deliberately excludes
`stock_reallocation` from `ALLOWED_MITIGATION_ACTIONS` ("needs multi-site
transfer logic... excluded here rather than left as an approvable action
with nothing to execute it"), and nothing in the system otherwise ever
checks whether *other* sites hold surplus stock of a product a case's site
is short on. This agent surfaces that as an advisory signal only.

- **Purpose**: check whether other sites hold surplus on-hand stock of the
  same product a deficit site is short on, as extra evidence for a human
  decision-maker - never as a recommendation to act.
- **Responsibilities**: call `list_inventory_positions` (excluding the
  deficit site), assess whether any other site's on-hand quantity is
  meaningfully above its own safety stock target, and report the signal.
- **Inputs**: `case_id`, `product_id`, `deficit_site_id` (via
  `run_reallocation_scout`).
- **Outputs**: `{available: bool, evidence: str, candidate_sites: list[str], confidence: float 0-1}`.
- **Sub-agents**: none.
- **Tools**: `list_inventory_positions` (read-only, `inventory_mcp`) - the
  only tool it is given (least privilege).
- **MCP dependencies**: `inventory_mcp`.
- **Guardrails**:
  - invoked only by the Inventory Agent's own deterministic code (not model
    discretion), and only for a contributing `thin_safety_stock` finding.
  - strictly read-only: no write tool for reallocation exists anywhere in
    the system, so this agent's output cannot itself mutate any state.
  - advisory-only by design and by prompt: the system prompt explicitly
    forbids claiming a transfer occurred or recommending one be executed.
  - no escalation path: `stock_reallocation` is absent from
    `ALLOWED_MITIGATION_ACTIONS`, so even if a future Decision Agent change
    tried to propose it as an action, Guardrail Gate A
    (`guardrails/policy.py::gate_a_pre_approval`) denies it by name - see
    `tests/test_mcp_workflow_audit.py::test_create_approval_request_denied_stock_reallocation`.
  - bounded cost: `max_turns=3` (tighter than the shared default of 6 -
    this is a narrow, single-tool task).
- **Hooks**: none of its own.
- **Skills**: none from `skills.py` - its output contract is inlined in its
  own system prompt since it's the only agent that uses it (`skills.py`
  exists to avoid duplicating wording across *multiple* agents).
- **Human approval requirements**: none - it is read-only and produces no
  executable action.
- **Failure handling**: an `MCPToolError` from `list_inventory_positions`
  surfaces to the model as an `is_error` tool result, same as every other
  agent in this codebase; `ToolCallingAgent.run()` raises `RuntimeError` if
  the model exhausts `max_turns` without a final answer. Either way, the
  calling Inventory Agent catches both and degrades gracefully - the
  primary inventory finding is still returned, just without a
  `reallocation_signal` key.
- **Audit requirements**: `list_inventory_positions` is audited by the tool
  itself (`inventory_server.py` calls `record_event()`); the agent writes
  nothing to the audit log directly.
- **Evaluation criteria**: given a surplus position at another site,
  returns `available: true` naming that site in `candidate_sites`; given no
  other sites or no surplus anywhere, returns `available: false`. Covered
  by `tests/test_agents_investigation.py`
  (`test_reallocation_scout_finds_surplus_elsewhere`) and exercised end to
  end via the Inventory Agent's own tests.

## Usage

No manual wiring is needed - it runs automatically inside
`run_inventory_agent()` (`agents/inventory_agent.py`), itself called from
`orchestrator.py`'s normal investigation sequence, whenever a case's
Inventory Agent finding is a contributing `thin_safety_stock` case. Its
output appears as `findings["inventory"]["reallocation_signal"]` in the
case record and the dashboard's JSON viewer - purely as extra evidence for
the Decision Agent's prompt and a human approver's context.
`orchestrator._candidate_options()` is untouched, so this never introduces
a new option to approve or execute.

For manual/isolated testing outside a real case, use
`scripts/test_reallocation_scout.py <product_id> <deficit_site_id>`
(mirrors `scripts/test_manufacturing_agent.py`).
