# Decision Agent

`src/control_tower/agents/decision_agent.py`

- **Purpose**: synthesize the Demand/Inventory/Supply findings into 2-3
  ranked mitigation scenarios, pick a recommendation, and request human
  approval.
- **Responsibilities**: weigh findings against a deterministically-built
  list of candidate options (from the orchestrator - it may not invent an
  action or params outside that list); produce ranked scenarios with
  cost/lead-time/risk tradeoffs; call `create_approval_request` with its
  top recommendation.
- **Inputs**: `case_id`, `product_id`, `site_id`, `findings` (list of the
  three investigation agents' outputs), `candidate_options` (list of
  `{action_type, params}` the orchestrator determined are actually
  executable for this case).
- **Outputs**: `{scenarios: [...], recommended_action_type, recommended_params, approval_id, rationale}`.
  `approval_id` is `null` if Gate A denied the request.
- **Sub-agents**: none.
- **Tools**: `create_approval_request` (write - queues for approval, does
  not execute anything).
- **MCP dependencies**: `workflow_audit_mcp`.
- **Guardrails**: **Gate A** (`gate_a_pre_approval`) runs *inside*
  `create_approval_request` before anything is written - checks the case
  has no approval already in flight, the action type is authorized
  (`config.ALLOWED_MITIGATION_ACTIONS`), and the action's params are valid
  and reference real entities belonging to this case's product. This agent
  cannot bypass Gate A by reasoning around it; it can only get denied and
  must report the denial rather than retry with a different action (per its
  system prompt).
- **Hooks**: none (see Phase 1 architecture doc).
- **Skills**: none.
- **Human approval requirements**: this agent's entire output *is* the
  human-approval request; it does not itself approve or execute anything.
- **Failure handling**: a Gate A denial surfaces as an `is_error` tool
  result; the agent's final answer must explain the denial (its system
  prompt explicitly forbids retrying with a different action on its own).
- **Audit requirements**: `create_approval_request` audits both
  `SUCCESS` and `DENIED` outcomes itself; the orchestrator additionally
  writes a `decision_recorded` narrative event with the full decision
  payload.
- **Evaluation criteria**: given findings and a valid candidate list,
  produces a `PENDING` approval whose `action_type`/`params` exactly match
  one of the given candidates, and flips `Case.status` to
  `PENDING_APPROVAL`. Given an already-in-flight case, gets denied and
  leaves case state unchanged. Covered by
  `tests/test_agents_decision_execution.py`.
