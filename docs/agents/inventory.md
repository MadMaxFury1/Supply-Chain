# Inventory Agent

`src/control_tower/agents/inventory_agent.py`

- **Purpose**: investigate whether inventory-position factors (thin
  on-hand stock relative to safety stock, no timely replenishment) are
  contributing to a stockout risk case.
- **Responsibilities**: call `get_inventory_position` and
  `get_open_purchase_orders`, compare on-hand to safety stock, check
  whether any open PO would replenish stock in time, decide contribution.
- **Inputs**: `case_id`, `product_id`, `site_id`.
- **Outputs**: `{cause_category: str, evidence: str, confidence: float 0-1, contributes: bool}`,
  plus an optional `reallocation_signal` key (see Sub-agents) when the
  primary finding is a contributing `thin_safety_stock` case.
- **Sub-agents**: **Reallocation Scout** (`agents/reallocation_scout_agent.py`,
  spec: `docs/agents/reallocation-scout.md`). When this agent's own finding
  is `cause_category == "thin_safety_stock"` and `contributes == true`, it
  deterministically (plain Python `if`, not model discretion) calls the
  scout to check whether other sites hold surplus stock of the same
  product, and attaches the scout's structured output as
  `finding["reallocation_signal"]`. Purely advisory - see Guardrails.
- **Tools**: `get_inventory_position`, `get_open_purchase_orders` (both
  read-only).
- **MCP dependencies**: `inventory_mcp`.
- **Guardrails**:
  - none apply directly to this agent's own tools (read-only).
  - the sub-agent call is gated deterministically by this agent's own code,
    not left to model choice.
  - a Reallocation Scout failure (`MCPToolError`/`RuntimeError`) is caught
    here and never blocks or alters the primary finding - the enrichment is
    best-effort.
  - the scout's signal can never become an executable action: no MCP write
    tool exists for reallocation, and `stock_reallocation` is excluded from
    `ALLOWED_MITIGATION_ACTIONS` (`config.py`), so Guardrail Gate A denies it
    by name if anything ever tried (`guardrails/policy.py`, tested in
    `tests/test_mcp_workflow_audit.py::test_create_approval_request_denied_stock_reallocation`).
- **Hooks**: none of its own; see Demand Agent spec.
- **Skills**: `skills.investigation_finding_contract("inventory-position factors")`.
- **Human approval requirements**: none.
- **Failure handling**: same pattern as the Demand Agent -
  `MCPToolError` → `is_error` tool result, model decides how to proceed;
  `RuntimeError` on `max_turns` exhaustion.
- **Audit requirements**: both read tools audit themselves; the agent
  writes nothing directly.
- **Evaluation criteria**: given thin on-hand stock relative to safety
  stock plus a delayed PO, returns `contributes: true`. Covered by
  `tests/test_agents_investigation.py`
  (`test_inventory_agent_flags_thin_stock_and_attaches_reallocation_signal`,
  `test_inventory_agent_survives_reallocation_scout_failure`).
