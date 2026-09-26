# Supply Agent

`src/control_tower/agents/supply_agent.py`

- **Purpose**: investigate whether low supplier reliability is
  contributing to a stockout risk case.
- **Responsibilities**: call `get_supplier_status`, assess the relevant
  supplier's reliability, decide contribution.
- **Inputs**: `case_id`, `product_id`, `supplier_id`. `supplier_id` is
  resolved by the (deterministic) orchestrator from the case's open
  purchase orders and passed in - discovering it is not this agent's job.
- **Outputs**: `{cause_category: str, evidence: str, confidence: float 0-1, contributes: bool}`.
- **Sub-agents**: none.
- **Tools**: `get_supplier_status` (read-only).
- **MCP dependencies**: `supplier_mcp`.
- **Guardrails**: none apply directly (read-only).
- **Hooks**: none of its own; see Demand Agent spec.
- **Skills**: `skills.investigation_finding_contract("supplier reliability")`.
- **Human approval requirements**: none.
- **Failure handling**: same pattern as the other investigation agents.
- **Audit requirements**: the read tool audits itself.
- **Evaluation criteria**: given a low-reliability supplier, returns
  `contributes: true`. Covered by `tests/test_agents_investigation.py`. If
  the orchestrator finds no open PO to resolve a supplier from, it skips
  this agent entirely and supplies a fixed `no_supplier_on_record` /
  `contributes: false` finding instead.

## Scope note (Phase 2)

This agent used to also investigate delayed manufacturing orders via
`get_manufacturing_status`. That responsibility moved to the new
**Manufacturing Agent** (`docs/agents/manufacturing.md`) when Phase 2
introduced it, so this agent's scope was narrowed to supplier reliability
only - otherwise the new agent would have duplicated an existing one's
responsibility (CLAUDE.md Do-Not: "Duplicate agents or MCP tools"). See
`docs/architecture/phase2-manufacturing-agent.md`.
