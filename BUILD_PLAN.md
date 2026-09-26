# Build Plan

## Phase 0 — Project Foundation

Status: NOT STARTED

- [ ] Repository structure
- [ ] CLAUDE.md
- [ ] Configuration
- [ ] Logging
- [ ] Error handling
- [ ] Database
- [ ] Base domain models
- [ ] Agent interface
- [ ] Tool interface
- [ ] MCP interface
- [ ] Audit framework
- [ ] Test framework

---

## Phase 1 — Stockout Vertical Slice

Status: COMPLETE (scope reduced from the original list below - see notes;
documented per CLAUDE.md's "no silent architecture changes" rule and
recorded in full in `docs/architecture/phase1-stockout-slice.md`)

### Business

- [x] Stockout scenario — `scripts/generate_synthetic_data.py` seeds one
      reproducible case (PRD-0001 / SITE-DC-01 / SUP-03).
- [x] Business rules — deterministic days-of-supply threshold in
      `domain/risk_detector.py`; deterministic Gate A/B in
      `guardrails/policy.py`.
- [x] Synthetic data — SQLite (`data/control_tower.db`), Faker-generated,
      seeded scenario verified to cross the risk threshold.

### Agents

Reduced from 7 to 6 - **Orchestrator** is deterministic code
(`orchestrator.py`), not an LLM agent, and **Governance Agent** was folded
into the deterministic **Guardrails** module below (both changes match the
Do-Not rule: "don't create an agent where a deterministic service is
sufficient", and "never rely solely on LLM instructions for
security/authorization/compliance").

- [x] Orchestrator — deterministic coordinator, `orchestrator.py`
- [x] Demand Agent — `agents/demand_agent.py`
- [x] Inventory Agent — `agents/inventory_agent.py`
- [x] Supply Agent — `agents/supply_agent.py`
- [x] Decision Agent — `agents/decision_agent.py`
- [x] Execution Agent — `agents/execution_agent.py`
- [x] ~~Governance Agent~~ — replaced by deterministic `guardrails/policy.py`

### MCP

Reduced from 5 servers to 3, grouped by trust boundary rather than by
domain. Planning is covered by `inventory_mcp`'s read tools; the audit log
is a first-class part of `workflow_audit_mcp` rather than a separate server.

- [x] Inventory MCP — `mcp_servers/inventory_server.py` (read-only)
- [x] Supplier MCP — `mcp_servers/supplier_server.py` (read + the only
      write/execution tools in the system)
- [x] Workflow MCP — `mcp_servers/workflow_audit_server.py` (approval queue)
- [x] Audit MCP — folded into Workflow MCP (`write_audit_event`,
      `get_audit_trail`)
- [x] ~~Planning MCP~~ — covered by Inventory MCP's `get_demand_forecast`

### Guardrails

- [x] Tool authorization — least-privilege `tools_for()` scoping per agent
      in `agents/base.py`
- [x] Data access — agents only ever reach data through MCP tools
- [x] Action authorization — Gate A (`gate_a_pre_approval`) and Gate B
      (`gate_b_pre_execution`) in `guardrails/policy.py`, enforced *inside*
      the MCP write-tool handlers, not just orchestration code
- [x] Human approval — async CLI (`scripts/approve.py`), backed by
      `create_approval_request` / `resolve_approval`
- [x] Audit — every MCP tool handler calls `audit/trail.record_event()` as
      part of its own transaction

### Hooks

Authorization/validation/audit are still enforced by the guardrail gates
and `record_event()` inside the MCP tool handlers (not by hooks - per
CLAUDE.md those must be enforceable at runtime, not deterministic-but-
skippable side calls). `hooks.py` adds simple lifecycle notification
hooks alongside them: deterministic, observable (logged), fail-safe
(never propagate an exception into the pipeline that fired them).

- [x] `on_case_opened` — fired by `risk_detector.detect_stockout_risks()`
      when a new case is opened
- [x] `on_case_closed` — fired by `workflow_audit_mcp.close_case`
- [x] Pre-tool authorization — covered by Gate A/B (see Guardrails)
- [x] Pre-tool validation — covered by Gate A/B (see Guardrails)
- [x] Post-tool audit — covered by `record_event()` in every tool handler
- [x] Post-action verification — covered by Execution Agent's read-tool
      verification step

### Skills

`skills.py` holds shared prompt fragments agents are equipped with
(distinct from tools - injected text, not an MCP call).

- [x] Investigation finding contract — the shared structured-JSON output
      contract used by the Demand, Inventory, and Supply agents
      (`investigation_finding_contract()`), so the three don't duplicate
      identical wording
- [ ] Scenario analysis skill — decision_agent.py's own system prompt
      covers this; not factored out since only one agent uses it

### Testing

- [x] Unit tests — `tests/test_risk_detector.py`
- [x] Agent tests — `tests/test_agents_investigation.py`,
      `tests/test_agents_decision_execution.py` (stubbed LLM, real tools)
- [x] MCP tests — `tests/test_mcp_inventory.py`, `test_mcp_supplier.py`,
      `test_mcp_workflow_audit.py`
- [x] Guardrail tests — denial paths covered directly in the MCP tests
      (Gate A/B have no separate LLM surface to test independently)
- [x] End-to-end scenario — `tests/test_orchestrator.py`,
      `tests/test_e2e_scenario.py` (detect → investigate → decide →
      approve → execute → verify → close, plus idempotency)

---

## Phase 2 — Manufacturing

Status: IN PROGRESS (1 of 4 agents built). Building the Manufacturing
Agent required narrowing the existing Supply Agent's scope (it used to
also investigate manufacturing-order delays) to avoid duplicating agents/
tools per CLAUDE.md's Do-Not rule - documented in full in
`docs/architecture/phase2-manufacturing-agent.md`.

- [x] Manufacturing Agent — `agents/manufacturing_agent.py`
- [ ] Capacity Agent
- [ ] Material Availability Agent
- [ ] Scheduling Agent
- [x] Manufacturing MCP — `mcp_servers/manufacturing_server.py` (read-only;
      home for the remaining Phase 2 agents' tools too)

### Cross-cutting addition: Reallocation Scout sub-agent

Not one of the 4 planned Phase 2 agents above - a small, targeted addition
under the existing Inventory Agent, called out here per CLAUDE.md's "no
silent architecture change" rule (same precedent Phase 1/2 used for their
own scope changes).

- [x] Reallocation Scout — `agents/reallocation_scout_agent.py`, the first
      sub-agent in the codebase (every other agent spec previously said
      "Sub-agents: none"). Read-only, advisory-only: checks whether other
      sites hold surplus stock of a product a case's site is short on, and
      attaches the result to the Inventory Agent's finding as
      `reallocation_signal`. Fills the gap left by `stock_reallocation`
      being deliberately excluded from `ALLOWED_MITIGATION_ACTIONS`
      (`config.py`) - it surfaces the signal without ever being able to
      trigger an action, since no execution tool for it exists and Gate A
      denies that action_type by name. Full spec:
      `docs/agents/reallocation-scout.md`. New tool:
      `inventory_mcp.list_inventory_positions` (`docs/mcp/inventory.md`).

---

## Phase 3 — Logistics

- [ ] Logistics Agent
- [ ] Shipment Agent
- [ ] ETA Agent
- [ ] Expedite Agent
- [ ] Cold Chain Agent
- [ ] TMS MCP
- [ ] IoT MCP

---

## Phase 4 — Quality

- [ ] Quality Agent
- [ ] QC Agent
- [ ] Deviation Agent
- [ ] CAPA Agent
- [ ] Batch Release Agent
- [ ] QMS MCP
- [ ] LIMS MCP
- [ ] Batch Record MCP

---

## Phase 5 — Regulatory

- [ ] Regulatory Agent
- [ ] Market Authorization Agent
- [ ] Supplier Qualification Agent
- [ ] Regulatory MCP

---

## Phase 6 — Full Control Tower

- [ ] Exception dashboard
- [ ] Agent activity
- [ ] Decision center
- [ ] Approval center
- [ ] Audit center
- [ ] Supply-chain risk view
- [ ] Scenario simulation

---

## Phase 7 — Learning

- [ ] Outcome tracking
- [ ] Root-cause analysis
- [ ] Agent evaluation
- [ ] Process improvement
- [ ] Continuous learning
