# Manufacturing Agent

`src/control_tower/agents/manufacturing_agent.py`

- **Purpose**: investigate whether delayed manufacturing orders are
  contributing to a stockout risk case for a specific product.
- **Responsibilities**: call `get_manufacturing_status`, check whether any
  in-flight manufacturing orders for the product are delayed and whether
  their planned completion dates put supply at risk, decide whether
  manufacturing is a meaningful contributor, and explain why.
- **Inputs**: `case_id`, `product_id` (via `run_manufacturing_agent`).
- **Outputs**: `{cause_category: str, evidence: str, confidence: float 0-1, contributes: bool}`.
- **Sub-agents**: none.
- **Tools**: `get_manufacturing_status` (read-only).
- **MCP dependencies**: `manufacturing_mcp`.
- **Guardrails**: none apply directly - it only calls a read-only tool with
  no write/authorization surface.
- **Hooks**: none of its own; `hooks.on_case_opened` fires upstream when
  the orchestrator's case was created by `risk_detector`, not by this agent.
- **Skills**: `skills.investigation_finding_contract("manufacturing order delays")`
  - the shared structured-finding JSON contract also used by the
  Demand, Inventory, and Supply agents.
- **Human approval requirements**: none - investigation is read-only.
- **Failure handling**: an `MCPToolError` from the tool call surfaces to the
  model as an `is_error` tool result so it can report the failure in its
  final answer rather than crash; `ToolCallingAgent.run()` raises
  `RuntimeError` if the model exhausts `max_turns` without a final answer.
- **Audit requirements**: every `get_manufacturing_status` call is audited
  by the tool itself (`manufacturing_server.py` calls `record_event()`);
  the agent writes nothing to the audit log directly.
- **Evaluation criteria**: given a delayed manufacturing order whose
  planned completion date is close to or past the case's risk window,
  returns `contributes: true` with a `manufacturing_delay`-shaped category
  and evidence quoting the MO's status/date; given no MOs or on-time MOs,
  returns `contributes: false`. Covered by `tests/test_agents_investigation.py`
  with a stubbed LLM (real tool calls, real DB).

## Relationship to the Supply Agent

Introduced in Phase 2. Manufacturing-order investigation previously lived
inside the Supply Agent (`docs/agents/supply.md`); it was moved here to
avoid one agent covering two distinct root-cause domains, and to avoid
this new agent duplicating an existing agent's responsibility (CLAUDE.md
Do-Not: "Duplicate agents or MCP tools"). See
`docs/architecture/phase2-manufacturing-agent.md` for the full rationale.
