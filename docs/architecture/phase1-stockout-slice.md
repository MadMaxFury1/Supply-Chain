# Phase 1 — Stockout Vertical Slice: Architecture

## Purpose

End-to-end vertical slice of the Control Tower architecture: detect a
critical-product stockout risk, investigate root cause with specialized
agents, generate ranked mitigation scenarios, gate on deterministic
guardrails, get human approval, execute, verify, and record a complete
audit trail.

## Flow

```
risk_detector (deterministic)
    → opens Case
orchestrator (deterministic)
    → Demand Agent    ─┐
    → Inventory Agent  ├─ investigate in parallel-equivalent sequence, each via MCP read tools
    → Supply Agent     ─┘
    → Decision Agent  → create_approval_request (Gate A, inside the tool)
                            → Case.status = PENDING_APPROVAL
[human, async CLI: scripts/approve.py]
    → resolve_approval → Case.status = APPROVED | REJECTED
    → Execution Agent → create_expedite_shipment | create_emergency_po (Gate B, inside the tool)
                            → Case.status = EXECUTING
                       → verifies via a read tool
                       → close_case → Case.status = CLOSED
```

Every step above that touches enterprise data or writes state does so
through one of the three MCP servers; every MCP tool handler writes its own
audit event as part of the same DB transaction. `get_audit_trail(case_id)`
returns the complete ordered record.

## Scope reduction from BUILD_PLAN.md (documented per the Do-Not rule against silent architecture changes)

BUILD_PLAN.md's original Phase 1 lists 7 agents and 5 MCP servers. This
slice implements 6 agents and 3 MCP servers:

- **Orchestrator is deterministic code** (`orchestrator.py`), not an LLM
  agent. It sequences the investigation agents, builds the candidate
  mitigation options, and narrates progress to the audit trail. Per
  CLAUDE.md Principle 3 and the Do-Not rule ("don't create an agent where a
  deterministic service is sufficient"), there is no reasoning here that
  needs an LLM.
- **Governance Agent was replaced by a deterministic guardrail module**
  (`guardrails/policy.py`), per CLAUDE.md's explicit rule that
  security/authorization/compliance must never rely solely on LLM
  instructions. Its two gates (`gate_a_pre_approval`, `gate_b_pre_execution`)
  are called *inside* the MCP write-tool handlers themselves, so the
  enforcement boundary is the tool, not agent discipline or orchestration
  code that a bug could route around.
- **5 MCP servers became 3**, grouped by trust boundary rather than by
  domain: `inventory_mcp` (read-only enterprise data), `supplier_mcp` (read
  status + the only two write/execution tools in the system), and
  `workflow_audit_mcp` (the approval queue and the audit log - "Planning
  MCP" and "Audit MCP" from the original list are covered by
  `get_demand_forecast` and `write_audit_event`/`get_audit_trail`
  respectively).
- **Hooks and Skills are minimal, not separate frameworks.**
  Authorization/validation/audit stay in the guardrail gates and
  `record_event()` calls per CLAUDE.md ("must be enforceable at runtime");
  `hooks.py` adds two small deterministic, observable, fail-safe lifecycle
  notification hooks (`on_case_opened`, `on_case_closed`) alongside them.
  `skills.py` holds one shared prompt fragment
  (`investigation_finding_contract`) used by the Demand/Inventory/Supply
  agents so they don't duplicate identical output-contract wording.
- **`stock_reallocation` was dropped as an allowed mitigation action.**
  Building it would need multi-site inventory transfer logic out of scope
  for this slice; excluding it from `config.ALLOWED_MITIGATION_ACTIONS`
  keeps every action the Decision Agent can recommend backed by a real
  execution tool, rather than leaving an approvable action with nothing to
  execute it.

## Key design decisions

- **Idempotency has no separate key store.** `gate_b_pre_execution` flips
  `Case.status` to `EXECUTING` atomically on success, so a retried/duplicate
  execution call is denied on its second attempt because the case is no
  longer `APPROVED`. `resolve_approval` similarly checks
  `Approval.status == "PENDING"` before deciding, so a repeated `approve`
  CLI invocation can't re-trigger execution.
- **Human approval is async, not a blocking prompt.** `scripts/run_detection.py`
  detects and investigates a case, then stops at "awaiting approval".
  `scripts/approve.py <case_id> --approve|--reject` is a separate
  invocation a human runs on their own schedule.
- **Agents never touch the database directly.** Only deterministic modules
  (`risk_detector.py`, `guardrails/policy.py`, `orchestrator.py`,
  `audit/trail.py`) do; the six LLM agents reach all enterprise data and
  every state-changing action exclusively through MCP tools
  (`agents/base.py`'s `ToolCallingAgent`).
- **Two interchangeable tool dispatchers.** `InProcessToolDispatcher` calls
  the MCP server objects directly in-process (used by agent-behavior and
  end-to-end tests, no subprocess overhead). `StdioToolDispatcher` spawns
  each MCP server as a real subprocess and talks the real MCP stdio
  protocol (used by the production CLI scripts). Agent code is written
  against the same small `list_tools`/`call` interface either way.
- **The application's LLM calls use whatever Anthropic credentials are
  already configured in the environment.** `agents/base.py`'s default
  `llm_call` constructs `anthropic.Anthropic()` with no explicit
  arguments, so the SDK resolves `ANTHROPIC_API_KEY` (or
  `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`) from the environment itself.

## Files

```
scripts/generate_synthetic_data.py   synthetic life-sciences dataset + seeded scenario
                                      + CSV export to `test data/`
scripts/run_detection.py             CLI: detect → orchestrate → request approval
scripts/approve.py                   CLI: approve/reject → execute → verify → close

dashboard/app.py                     Streamlit UI (cases, audit trail, CSV upload to
                                      reload tables, "run detection" button, and
                                      Approve/Reject buttons for pending approvals)
.streamlit/config.toml               dashboard theme (light grey / red)
test data/                           CSV export of the synthetic dataset, one file per
                                      table - re-upload via the dashboard to reload it

src/control_tower/config.py
src/control_tower/db/{models.py,session.py}
src/control_tower/domain/risk_detector.py              deterministic detection
src/control_tower/guardrails/policy.py                 deterministic Gate A / Gate B
src/control_tower/audit/trail.py                       shared audit-write/-read helpers
src/control_tower/orchestrator.py                       deterministic coordinator
src/control_tower/hooks.py                              on_case_opened / on_case_closed
src/control_tower/skills.py                             shared agent prompt fragments

src/control_tower/mcp_servers/inventory_server.py
src/control_tower/mcp_servers/supplier_server.py
src/control_tower/mcp_servers/workflow_audit_server.py

src/control_tower/agents/base.py            shared tool-calling harness (dispatchers + loop)
src/control_tower/agents/demand_agent.py
src/control_tower/agents/inventory_agent.py
src/control_tower/agents/supply_agent.py
src/control_tower/agents/decision_agent.py
src/control_tower/agents/execution_agent.py

tests/                                unit, MCP, agent-behavior, and end-to-end tests
```

## Running it

```bash
python scripts/generate_synthetic_data.py --reset   # seed the DB + write test data/*.csv
python scripts/run_detection.py                     # detect + investigate + decide
python scripts/approve.py <case_id> --approve       # execute + verify + close

streamlit run dashboard/app.py                      # local dashboard, http://localhost:8501
```

Real agent runs need Anthropic credentials already present in the
environment (`ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN`/
`ANTHROPIC_BASE_URL`) - the SDK picks them up itself, nothing further to
set. `pytest` runs the full test suite (39 tests at the time of writing)
without needing any credentials - all agent-behavior and end-to-end tests
stub the LLM call and exercise the real MCP tools/guardrails/DB.

The dashboard is a human-facing reporting/ops UI, not an LLM agent, so - per
the same precedent as `risk_detector.py`/`guardrails/policy.py`/
`orchestrator.py` - it reads the DB directly rather than through MCP. Its
CSV upload feature replaces the matching table(s) with the uploaded rows
(matched by filename against `test data/`'s schema) and its "Run detection
now" button just shells out to `scripts/run_detection.py`, so no detection
logic is duplicated in the UI.

**Human approval in the dashboard.** When a selected case has a `PENDING`
approval, the case-detail view shows a "Human approval required" panel with
the recommended action (`recommended_action_json`), a "Decided by" field, an
optional note, and **Approve**/**Reject** buttons. Exactly like "Run
detection now", these buttons don't reimplement Gate B, execution, or
verification in Streamlit - they shell out to
`scripts/approve.py <case_id> --approve|--reject --decided-by ... [--note ...]`
and display its combined stdout/stderr, so the dashboard is an alternative
front-end onto the same audited CLI path, not a second approval mechanism.
After approval the Execution Agent runs synchronously inside that
subprocess call (execute → verify → close), so the panel's output shows the
full result before the button click returns.
