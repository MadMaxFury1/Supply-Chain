# Demand Agent

`src/control_tower/agents/demand_agent.py`

- **Purpose**: investigate whether demand-side factors (spike, sustained
  forecast error, trend shift) are contributing to a stockout risk case for
  a specific product/site.
- **Responsibilities**: call `get_demand_forecast`, compare recent actual
  vs. forecast demand, decide whether demand is a meaningful contributor,
  and explain why.
- **Inputs**: `case_id`, `product_id`, `site_id` (via `run_demand_agent`).
- **Outputs**: `{cause_category: str, evidence: str, confidence: float 0-1, contributes: bool}`.
- **Sub-agents**: none.
- **Tools**: `get_demand_forecast` (read-only).
- **MCP dependencies**: `inventory_mcp`.
- **Guardrails**: none apply directly - it only calls a read-only tool with
  no write/authorization surface.
- **Hooks**: none of its own; `hooks.on_case_opened` fires upstream when
  the orchestrator's case was created by `risk_detector`, not by this agent.
- **Skills**: `skills.investigation_finding_contract("demand-side factors")`
  - the shared structured-finding JSON contract also used by the
  Inventory and Supply agents.
- **Human approval requirements**: none - investigation is read-only.
- **Failure handling**: an `MCPToolError` from the tool call surfaces to the
  model as an `is_error` tool result so it can report the failure in its
  final answer rather than crash; `ToolCallingAgent.run()` raises
  `RuntimeError` if the model exhausts `max_turns` without a final answer.
- **Audit requirements**: every `get_demand_forecast` call is audited by
  the tool itself (`inventory_server.py` calls `record_event()`); the
  agent writes nothing to the audit log directly.
- **Evaluation criteria**: given a real demand spike, returns
  `contributes: true` with a `demand_spike`-shaped category and evidence
  quoting the actual numbers observed; given flat demand, returns
  `contributes: false`. Covered by `tests/test_agents_investigation.py`
  with a stubbed LLM (real tool calls, real DB).
