# Claude Code Project Instructions

## Project

Pharma Supply Chain Autonomous Control Tower — a production-oriented
multi-agent platform for pharmaceutical supply-chain exception management.

## Read Before Coding

1. CLAUDE.md
2. BUILD_PLAN.md
3. Relevant architecture, agent, MCP, guardrail, and workflow specs

## Architecture

```
User → Control Tower → Orchestrator → Domain Agents → Sub-Agents
     → Decision Agent → Guardrails → Human Approval → Execution Agent
     → MCP → Enterprise Systems
```

**Principles**
1. Agents reason; tools execute — no direct DB/enterprise-system access from agents.
2. Enterprise capabilities are exposed only via typed MCP tools.
3. Deterministic logic (calculations, validation, authorization, business rules) stays outside the LLM.
4. Human approval is required for actions on regulated/consequential processes.
5. Every agent decision and tool call is auditable.
6. Agents get least-privilege tools and data access.
7. Fail closed: on authorization/validation/compliance failure, don't execute.
8. Docs are updated alongside architecture/behavior changes.

## Specs

**Agent spec** must define: purpose, responsibilities, inputs, outputs,
sub-agents, tools, MCP dependencies, guardrails, hooks, skills, human
approval requirements, failure handling, audit requirements, evaluation
criteria.

**MCP tool spec** must define: name, purpose, input/output schema,
authorization, validation, error handling, audit behavior, idempotency
(where applicable).

**Guardrails**: never rely solely on LLM instructions for
security/authorization/compliance — must be enforceable at runtime.

**Hooks**: must be deterministic, observable, fail safe.

## Testing

Minimum for new functionality: unit, integration, agent behavior, guardrail,
and MCP tests. Critical workflows also need scenario tests.

## Do Not

- Duplicate agents or MCP tools.
- Bypass guardrails or approval workflows.
- Hard-code credentials.
- Access enterprise databases directly from agents.
- Silently change architecture.
- Introduce a new framework without documenting why.
- Create an agent where a deterministic service would do.

## Development Process (per feature)

1. Read specs.
2. Identify dependencies.
3. Update docs if required.
4. Implement smallest viable change.
5. Add tests.
6. Run validation.
7. Update BUILD_PLAN.md.
8. Summarize changes and unresolved issues.
