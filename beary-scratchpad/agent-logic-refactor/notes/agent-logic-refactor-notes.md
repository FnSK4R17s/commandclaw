# Agent Logic Refactor -- Merged Research Notes

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-30
**Sources:** Q1 (LangGraph state/routing), Q2 (NeMo Guardrails), Q3 (code-based guardrails), Q4 (minimal system prompts)

---

## General Understanding Summary

The agent logic refactor moves CommandClaw from a prompt-heavy architecture -- where behavioral instructions (session detection, memory loading, heartbeats, guardrails, tool routing) are embedded in multi-thousand-token system prompts -- to a code-structural architecture using LangGraph's StateGraph, conditional edges, pre-processing nodes, and middleware hooks. The research converges on four pillars:

1. **LangGraph as runtime backbone**: StateGraph with typed state schemas replaces prompt-based session management. Conditional edges provide deterministic routing without LLM reasoning. Pre-processing nodes structurally guarantee memory loading and context injection before agent execution. Cron jobs replace prompt-instructed heartbeats. The Store API provides cross-session long-term memory with namespace-scoped semantic search.

2. **NeMo Guardrails as a layered safety middleware**: NVIDIA's open-source toolkit intercepts every message through a five-stage pipeline (input, dialog, retrieval, tool, output rails). Colang 2.0 provides stateful flow definitions. Integration with LangGraph is via `RunnableRails` wrapping graph nodes. Performance overhead is 20-100ms per request. PII detection is supported via Presidio, GLiNER, and Guardrails AI backends.

3. **Code-based guardrails for deterministic enforcement**: Credential leak prevention uses `detect-secrets` (via Guardrails AI `SecretsPresent`) and regex-based scanning. Dangerous command blocking uses AST-based bash parsing (`bashlex`) rather than fragile regex. PII scrubbing uses Microsoft Presidio's analyzer/anonymizer pipeline. The tripwire pattern (OpenAI Agents SDK) halts execution immediately on guardrail violation without LLM involvement.

4. **Minimal system prompts with behavior in code**: Production teams reduce system prompts to ~50 tokens (role + meta-instruction) by encoding behavior in tool descriptions, graph nodes, and LangChain 1.0 middleware (`before_model`, `modify_model_request`, `after_model`). Progressive skill loading replaces prompt-stuffing, cutting token consumption 75-90%. The key insight: prompts describe *what* the agent is; code prescribes *how* it behaves.

---

## 1. LangGraph State Management, Conditional Routing, and Scheduled Tasks

### StateGraph and State Schema Architecture

LangGraph's `StateGraph` is built on typed Python structures (`TypedDict`, Pydantic `BaseModel`, or dataclasses) that define a shared state object flowing through all graph nodes [1]. Each node receives the full state and returns a partial update merged back via an immutability principle. For list-type fields that accumulate (e.g., message history), LangGraph uses reducer annotations [1]:

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]     # appends, not overwrites
    documents: list[str]
    counter: Annotated[int, add]                # accumulates
    session_type: str
    error_count: int
```

State validation should occur at node boundaries to catch errors early [2]. The `operator.add` reducer merges lists from parallel branches [3].

**Application to CommandClaw**: A session state schema can encode `session_type`, `heartbeat_due`, `memory_loaded`, and `user_id` as typed fields -- making these structural guarantees rather than prompt-injected instructions.

### Conditional Edges and Deterministic Routing

Conditional edges use a routing function that inspects state and returns a string key mapped to target nodes [1][4]:

```python
def route_by_session_type(state: AgentState) -> str:
    if state["session_type"] == "coding":
        return "coding_agent"
    elif state["session_type"] == "research":
        return "research_agent"
    return "general_agent"

builder.add_conditional_edges(
    "classify_session",
    route_by_session_type,
    {"coding_agent": "coding_agent", "research_agent": "research_agent",
     "general_agent": "general_agent"}
)
```

The routing function is pure Python -- no LLM call required. Nested conditional edges decompose complex decisions across sequential nodes [3]. Dynamic fan-out via the `Send` API creates parallel worker instances from state [1].

### Pre-Processing Nodes for Memory Loading and Context Injection

A pre-processing node runs before the main agent loop and loads context from persistent stores [5][6]:

```python
def load_memory(state: State, store: BaseStore):
    namespace = (state["user_id"], "preferences")
    prefs = store.search(namespace, query="agent instructions")
    return {"loaded_context": prefs}

builder.add_node("load_memory", load_memory)
builder.add_edge(START, "load_memory")
builder.add_edge("load_memory", "classify_session")
```

The `Store` API provides `put()`, `get()`, and `search()` with semantic search and filtering [5].

### Short-Term vs Long-Term Memory

**Short-term memory** (thread-scoped): persisted via checkpointers, scoped to a single conversation thread [5][6]:

```python
graph = builder.compile(checkpointer=PostgresSaver(conn))
result = graph.invoke(state, config={"configurable": {"thread_id": "session-123"}})
```

**Long-term memory** (cross-thread): uses `Store` with namespaces like `(user_id, "preferences")`. Supported backends include PostgreSQL (1,038 ops/sec), Redis, MySQL, SQLite [8].

**Multi-tenant scoping** pattern: `"tenant-{id}:user-{id}:session-{id}"` for thread IDs [2].

### Scheduled Tasks and Heartbeats via Cron Jobs

LangGraph Platform provides a first-class cron job API via `SyncCronClient` / `AsyncCronClient` [7][9]:

```python
cron_job = await client.crons.create_for_thread(
    thread_id=thread_id,
    assistant_id=assistant_id,
    schedule="*/10 * * * *",
    input={"messages": [{"role": "user", "content": "heartbeat check"}]}
)
```

Cron jobs run in the background. All schedules are UTC. Requires LangGraph API >= 0.5.18 [7].

Beyond cron, LangGraph supports event-based, state-based, time-based, and external triggers [10].

### Prompt-to-Structure Migration Table

| Prompt-based (current) | Graph-structural (LangGraph) |
|---|---|
| "Detect session type from first message" | `classify_session` node + conditional edge |
| "Load user memory at start" | `load_memory` pre-processing node |
| "Send heartbeat every 10 minutes" | Stateful cron job on thread |
| "If coding session, use tools X/Y" | Conditional edge routing to `coding_agent` subgraph |
| "Remember user preferences across sessions" | `Store` with `(user_id, "prefs")` namespace |

---

## 2. NVIDIA NeMo Guardrails -- Architecture, Guardrail Patterns, and Integration

### What NeMo Guardrails Is

NVIDIA NeMo Guardrails is an open-source (Apache 2.0) Python toolkit for adding programmable safety and control rails to LLM-based conversational systems. Current release: v0.21.0 (March 2025), supporting Python 3.10-3.13 [11][12].

### Architectural Overview

The architecture centers on the `LLMRails` orchestrator class with a five-stage processing pipeline [13]:

```
User Input -> Input Rails -> Dialog Rails -> Retrieval Rails ->
LLM Generation -> Tool Rails -> Output Rails -> Bot Response
```

`RailsConfig` aggregates all configuration from YAML and Colang files. The system is event-driven with all interactions modeled as discrete events [13].

### The Five Rail Types

1. **Input Rails** -- Applied before LLM processing. Jailbreak detection, prompt injection prevention, PII masking [11][13].
2. **Dialog Rails** -- Influence LLM prompting and conversation flow. Three intent detection modes: multi-step, single-call, embeddings-only [13].
3. **Retrieval Rails** -- Applied to RAG-retrieved chunks before they reach the LLM [13].
4. **Execution (Tool) Rails** -- Validate tool calls before execution and tool results before passing to LLM. Critical: tool messages are NOT subject to input rail validation by default [19][20].
5. **Output Rails** -- Applied to LLM responses before reaching the user. Support LLM self-checks, fact verification, PII masking [11][13].

### Colang 2.0

Colang 2.0 is a complete overhaul with three core abstractions (flows, events, actions) and Python-like syntax. It supports 50+ event types, parallel flow heads, and LLM-generated flows [15][16][17].

### PII Detection

NeMo Guardrails supports PII detection through multiple backends: GLiNER (v0.20.0+), Microsoft Presidio, Private AI, and Guardrails AI validators [11][13][14][18].

### LangChain and LangGraph Integration

`RunnableRails` wraps any LangChain Runnable with guardrails. Each agent in a multi-agent system can have its own guardrail configuration. Key limitation: RunnableRails produces single large chunks rather than token-level streaming [19].

In v0.21.0, `GuardrailsMiddleware` provides more seamless LangChain agent integration [14].

### Performance

20-100ms latency per request [22]. Optimizations: parallel rail execution (v0.21.0), single-call dialog mode, lazy embedding initialization, in-memory LFU caching (v0.18.0), streaming with chunked output rails [14][23].

### Deployment

Entirely self-hosted. Runs as embedded Python library or standalone FastAPI server with OpenAI-compatible endpoints [11][13].

---

## 3. Production Code-Based Guardrails

### Prompt-Based vs Code-Based Guardrails

Code-based guardrails operate as middleware or hooks that intercept data at well-defined lifecycle points. Prompt-based guardrails are necessary but insufficient: they can be bypassed via prompt injection, jailbreaking, or model hallucination [26][27].

The OpenAI Agents SDK formalizes the **tripwire pattern**: guardrail functions return `GuardrailFunctionOutput` with `tripwire_triggered`, halting execution immediately [28].

### Credential and Secrets Detection

**Guardrails AI** `SecretsPresent` validator wraps `detect-secrets` with entropy-based detection and regex patterns for known key formats (AWS, Slack, Stripe) [29].

**LLM Guard** (Protect AI) provides `Secrets` scanner and `Sensitive` output scanner [30].

**Claude Code hooks** enforce credential detection at file-write level via regex in PreToolUse hooks [31].

### Dangerous Command Blocking

**Claude Code** implements deny lists in `settings.json` plus PreToolUse hooks [32].

**claude-code-bash-guardian** uses AST-based parsing via `bashlex` with five sequential checks: EnvironmentVariableCheck, PipeSecurityCheck, VariableCommandCheck, BlacklistCheck, PathAccessCheck. Detects wrapper-command bypass attempts (sudo, xargs, env, timeout) [33].

### LangChain Guardrail Architecture

Built-in PII middleware with four handling strategies: Redact, Mask, Hash, Block. Applied independently to inputs, outputs, and tool results. Custom guardrails use `before_agent()` and `after_agent()` hooks with `@hook_config(can_jump_to=["end"])` for early termination [27][34].

### Microsoft Presidio for PII Detection

Separates `AnalyzerEngine` (identification) and `AnonymizerEngine` (de-identification). Uses NER (spaCy), regex, rule-based logic, checksum validation. Custom recognizers for domain-specific patterns [36][37].

### Reversible Anonymization

TIAMAT Privacy Proxy: entity map pattern replaces PII with numbered placeholders, LLM sees sanitized text, client-side re-hydration restores originals [38].

### Bidirectional Scanning Gap

Most PII scrubbing focuses on input direction, but LLMs can hallucinate PII in output. Production systems must inspect traffic in both directions [39].

### Security Limitations

Hook-based guardrails can become attack surfaces (CVE-2025-59536, CVE-2026-21852, CVE-2026-24887). Guardrails are one layer in defense-in-depth [31][33].

---

## 4. Minimal System Prompts -- Moving Behavior from Prompts into Code

### The Case Against Prompt-Stuffing

Accuracy plateaus even as prompt length doubles [41]. Progressive skill loading reduces baseline prompt overhead from 20,000 tokens to 300-500 tokens (75-90% reduction) [42]:

- **Tier 1 (~500 tokens):** Lightweight skill catalog.
- **Tier 2 (~2,000 tokens, on-demand):** Full skill instructions via `load_skill()`.
- **Tier 3 (granular, on-demand):** Supporting reference files.

### Tool Descriptions as the Primary Behavior Driver

Anthropic's context engineering guide: tools define "the contract between agents and their information/action space." Well-crafted tool descriptions replace large swaths of system prompt instruction [43].

- Minimal overlap in functionality [43].
- Descriptive, unambiguous descriptions with self-documenting parameter names [43].
- Dynamic docstrings inject valid parameter values at runtime [42].

### LangChain 1.0 Middleware: The Three-Hook Model

1. **`before_model`:** Conversation summarization, dynamic context injection, rate limiting [47].
2. **`modify_model_request`:** Modify tools, prompts, model selection per-request [47][48].
3. **`after_model`:** Guardrails, content filtering, human-in-the-loop approval [47].

The pattern: prompts describe *what* the agent is; middleware prescribes *how* it behaves [47].

### The Sub-100-Token System Prompt

```
You are a [role]. Use your tools to accomplish tasks.
Review available tools before acting. Be direct and concise.
```

Works when tool descriptions carry the behavioral contract, graph nodes handle pre/post-processing, middleware hooks enforce guardrails, and skill loading provides domain knowledge on-demand [42][43][45][47].

### Behavior Placement Decision Framework

- **Deterministic and always-on** -> middleware (logging, rate limiting)
- **Conditional on state** -> conditional edges (error recovery routing)
- **Domain-specific and variable** -> tool descriptions + skill loading

Not all prompt logic needs to become graph complexity -- a well-designed tool interface within a simple ReAct loop can outperform an over-engineered graph [42].

---

## 5. Deeper Dive Notes

### DD Q1: Pre-Invocation Hooks in LangGraph

LangGraph supports three mechanisms for pre-invocation logic:

**1. Conditional Entry Points**: `add_conditional_edges(START, routing_function)` allows the graph to route to different initial nodes based on state inspection before any agent logic runs [51].

**2. Context Schema for Runtime Injection**: The `context_schema` parameter on `StateGraph` enables injecting non-state configuration (LLM provider, DB connection, user_id) at runtime without polluting the graph state [51]:

```python
@dataclass
class ContextSchema:
    llm_provider: str = "openai"

graph = StateGraph(State, context_schema=ContextSchema)
graph.invoke(inputs, context={"llm_provider": "anthropic"})
```

Access inside nodes via `runtime: Runtime[ContextSchema]` parameter [51][52].

**3. LangChain 1.0 Middleware**: The `before_model` decorator runs logic before every LLM call (conversation summarization, dynamic context injection, rate limiting). The `modify_model_request` decorator modifies tools, prompts, message lists, and model selection per-request without touching permanent state. These are distinct from graph nodes -- they operate inside the agent's ReAct loop [47][48].

### DD Q2: Checkpointer and Memory Scoping

**Thread-level scoping**: Every `graph.invoke()` call requires a `thread_id` in the config. The checkpointer stores full state snapshots keyed by `thread_id`, enabling multi-turn conversations. Different thread IDs = completely isolated conversation histories [52][53].

```python
config = {"configurable": {"thread_id": "user_123_session_1"}}
graph.invoke({"messages": [...]}, config)
```

**Checkpointer backends**:
- `InMemorySaver`: development only, lost on restart
- `SqliteSaver`: local persistence, from `langgraph-checkpoint-sqlite`
- `PostgresSaver`: production-grade, supports concurrent access, connection pooling recommended (match pool size to concurrency) [54]
- `RedisSaver`, `MongoDBSaver`: alternative production backends

All require `checkpointer.setup()` on first use for schema initialization [54].

**Per-user long-term memory**: Use the Store API with context schemas to scope memories by user_id across threads [52]:

```python
@dataclass
class Context:
    user_id: str

async def call_model(state: MessagesState, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    namespace = (user_id, "memories")
    memories = await runtime.store.asearch(namespace, query="preferences")
```

**Namespace isolation**: Namespaces act as hard isolation boundaries -- different tenants cannot access each other's data through the same store instance [52].

### DD Q3: Output Guardrails for API Keys, PII, and Sensitive Content

**NeMo Guardrails custom output actions**: Use the `@action` decorator with `output_mapping` to control blocking decisions. The `context` parameter provides access to `bot_message` for inspection [55]:

```python
@action(is_system_action=True, output_mapping=lambda value: not value)
async def check_output_for_secrets(context: Optional[dict] = None):
    bot_message = context.get("bot_message", "")
    # Regex patterns for API keys, tokens, passwords
    patterns = [
        r'(sk-[a-zA-Z0-9]{20,})',           # OpenAI keys
        r'(AKIA[0-9A-Z]{16})',               # AWS access keys
        r'(xoxb-[0-9]{11}-[0-9]{11}-\w+)',   # Slack tokens
        r'(ghp_[a-zA-Z0-9]{36})',            # GitHub PATs
    ]
    for p in patterns:
        if re.search(p, bot_message):
            return False  # Block
    return True  # Allow
```

Integrate in Colang: `$is_safe = execute check_output_for_secrets` [55].

**llm-guardrails library**: Rust/PyO3 hybrid with compiled regex for zero-copy pattern matching. Implements reversible redaction via entity maps (`<<EMAIL_1>>`, `<<PHONE_1>>`). Separate Rust modules for PII redaction, injection detection, bias scoring, and output validation [56].

```python
from llm_guardrails import GuardrailsPipeline
pipeline = GuardrailsPipeline()
pre = pipeline.pre_process(user_input)
post = pipeline.post_process(llm_response, pre.pii_mapping)
```

**Layered detection architecture** [57]:
1. Static layer: regex + substitution for known patterns, Unicode normalization
2. ML layer: lightweight classifiers (Llama Prompt Guard 2) for semantic threats
3. Schema layer: JSON schema validation for structured outputs

Output guardrails should apply regex scrubbing to redact leaked secrets before returning responses to clients [57].
