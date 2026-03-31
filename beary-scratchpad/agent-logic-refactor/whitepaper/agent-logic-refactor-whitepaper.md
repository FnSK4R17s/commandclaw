# Agent Logic Refactor: From Prompt-Based to Code-Structural Agent Behavior

**Author:** Background Research Agent (BEARY)
**Date:** 2026-03-30

---

## Abstract

This whitepaper presents the architectural case and implementation plan for refactoring CommandClaw's agent logic from a prompt-heavy design -- where session detection, memory loading, heartbeats, guardrails, and tool routing are encoded as natural-language instructions in a multi-thousand-token system prompt -- to a code-structural design using LangGraph's StateGraph, conditional edges, pre-processing nodes, LangChain 1.0 middleware hooks, and layered guardrails (NeMo Guardrails and/or custom code). The refactor eliminates prompt fragility (LLM forgetting or misinterpreting instructions), reduces per-request token consumption by 75-90%, and makes agent behavior deterministic, testable, and observable. We evaluate NeMo Guardrails against custom guardrail implementations, propose a concrete graph architecture, and provide a migration path from the current prompt-based system.

---

## 1. Introduction: Why Move from Prompt-Based to Code-Based Agent Behavior

CommandClaw's current architecture embeds behavioral logic in the system prompt: session type detection, memory file loading, heartbeat scheduling, credential leak prevention, dangerous command blocking, and tool routing are all expressed as natural-language instructions. This design has three fundamental limitations:

**Fragility.** LLMs do not reliably follow long prompt instructions. As prompt length doubles, accuracy plateaus [41]. Instructions compete for attention with conversation context, and the model may forget, reinterpret, or selectively ignore rules -- particularly under long conversations or complex tool-calling sequences.

**Token cost.** A system prompt embedding 10 behavioral "skills" at 2,000 tokens each consumes 20,000 tokens per request, regardless of whether those skills are relevant. Progressive skill loading can reduce this to 300-500 tokens baseline [42], but the fundamental issue remains: behavioral enforcement via prompt is wasteful.

**Non-determinism.** Prompt-based guardrails ("never output API keys") rely on the model's compliance. They can be bypassed via prompt injection, jailbreaking, or hallucination [26][28]. There is no guarantee of enforcement, no testable contract, and no observability into whether a guardrail was applied.

The alternative is **flow engineering** [41]: designing control flow, state transitions, and decision boundaries *around* LLM calls rather than optimizing the calls themselves. LangGraph provides the runtime for this approach, encoding agent behavior as a graph of typed nodes, conditional edges, and middleware hooks -- with the system prompt reduced to identity and meta-instructions (~50 tokens).

---

## 2. LangGraph Runtime Architecture

### 2.1 StateGraph and Typed State

LangGraph's `StateGraph` is parameterized by a typed Python structure (`TypedDict`, Pydantic `BaseModel`, or dataclass) that defines the shared state flowing through all nodes. Each node receives the full state and returns a partial update that is merged back [1].

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

class CommandClawState(TypedDict):
    messages: Annotated[list, add_messages]
    session_type: str                    # "coding" | "research" | "general"
    user_id: str
    memory_loaded: bool
    heartbeat_due: bool
    vault_context: list[str]
    trigger_source: str                  # "user" | "scheduler" | "webhook"
    guardrail_violations: list[str]
```

The `add_messages` reducer appends new messages rather than overwriting the list [1]. Without it, each node that touches `messages` would destroy conversation history.

### 2.2 Conditional Edges and Deterministic Routing

Conditional edges replace prompt-based routing ("if this is a coding session, use tools X/Y") with pure-Python functions that inspect state and return a target node name [1][4]:

```python
def route_after_classify(state: CommandClawState) -> Literal[
    "coding_agent", "research_agent", "general_agent"
]:
    return state["session_type"]

def route_by_trigger(state: CommandClawState) -> Literal[
    "heartbeat_handler", "load_memory"
]:
    if state["trigger_source"] == "scheduler":
        return "heartbeat_handler"
    return "load_memory"

builder.add_conditional_edges(START, route_by_trigger)
builder.add_conditional_edges("classify_session", route_after_classify)
```

No LLM call is required for routing. The function is testable in isolation with synthetic state. Dynamic fan-out via the `Send` API creates parallel worker instances when needed [1].

### 2.3 Pre-Processing Nodes

Pre-processing nodes run before the main agent loop, loading context from persistent stores and classifying the session [5][6]:

```
                    +-------------------+
                    |   route_by_trigger |
                    +--------+----------+
                             |
              +--------------+--------------+
              |                             |
    +---------v---------+        +----------v-----------+
    |   load_memory     |        | heartbeat_handler    |
    +--------+----------+        +----------------------+
             |
    +--------v----------+
    | classify_session   |
    +--------+----------+
             |
    +--------v----------+
    | inject_vault_ctx   |
    +--------+----------+
             |
    +--------v----------+     +-----+     +---------+
    | route_after_classify+-->|agent|---->|guardrails|-->END
    +----+-------+------+     +-----+     +---------+
         |       |
    coding  research  general
```

The `load_memory` node reads user preferences and session history from the Store before the agent processes any input:

```python
async def load_memory(state: CommandClawState, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    namespace = (user_id, "preferences")
    prefs = await runtime.store.asearch(namespace, query="agent instructions")
    namespace_history = (user_id, "session_history")
    history = await runtime.store.asearch(namespace_history, query="recent")
    return {"vault_context": [item.value for item in prefs], "memory_loaded": True}
```

### 2.4 Context Schema for Runtime Injection

The `context_schema` parameter on `StateGraph` enables injecting non-state configuration (user_id, LLM provider, database connection) at runtime without polluting graph state [51]:

```python
@dataclass
class CommandClawContext:
    user_id: str
    llm_provider: str = "anthropic"
    vault_path: str = "/apps/commandclaw-vault"

graph = StateGraph(CommandClawState, context_schema=CommandClawContext)

# At invocation:
graph.invoke(
    {"messages": [user_msg], "trigger_source": "user"},
    config={"configurable": {"thread_id": "session-abc"}},
    context=CommandClawContext(user_id="shikhar")
)
```

Nodes access context via `runtime: Runtime[CommandClawContext]` [51][52].

### 2.5 The Store API for Long-Term Memory

The Store provides cross-thread persistent memory with namespace-scoped semantic search [5][52]:

```python
# Write a user preference
await runtime.store.aput(
    namespace=("shikhar", "preferences"),
    key="code_style",
    value={"data": "Prefers Black formatter, 88-char lines, type hints"}
)

# Semantic search across preferences
items = await runtime.store.asearch(
    namespace=("shikhar", "preferences"),
    query="formatting preferences",
    limit=5
)
```

**Namespace hierarchy for CommandClaw**:

```
(user_id, "preferences")          # Cross-session user prefs
(user_id, "session_history")      # Summaries of past sessions
(user_id, "vault_index")          # Index of vault files
("system", "agent_instructions")  # Shared agent rules
```

Production backends: PostgresStore (recommended, 1,038 ops/sec), RedisStore, MongoDBSaver [8][52]. Namespaces act as hard isolation boundaries -- different users cannot access each other's data [52].

---

## 3. Minimal System Prompts

### 3.1 What Stays in the Prompt (~50 Tokens)

The system prompt reduces to identity and meta-instructions:

```
You are CommandClaw, a senior software engineering agent.
Use your tools to accomplish tasks. Review available tools
before acting. Be direct and concise.
```

Everything else -- behavioral rules, guardrails, memory loading, session routing -- moves to code [42][43][47].

### 3.2 What Moves to Code

| Current prompt instruction | Code replacement | Mechanism |
|---|---|---|
| "You are a coding assistant" | System prompt (retained) | Identity |
| "Detect session type from first message" | `classify_session` node | Graph node |
| "Load user memory files at start" | `load_memory` node | Graph node + Store API |
| "Send heartbeat every 10 minutes" | Cron job on thread | LangGraph Platform cron |
| "Never output API keys" | Output guardrail | NeMo rail or custom action |
| "Block rm -rf commands" | PreToolUse hook | bashlex AST parsing |
| "If coding session, use tools X/Y" | Conditional edge | `route_after_classify` |
| "Summarize long conversations" | `before_model` middleware | LangChain 1.0 |
| "Use efficient reasoning for simple queries" | `modify_model_request` middleware | LangChain 1.0 |

### 3.3 Tool Descriptions as Behavioral Contracts

Tool descriptions carry the behavioral contract -- what to do, when, with what inputs [43][44]. This eliminates the need for system prompt instructions about tool usage:

```python
@tool
def read_vault_file(path: str) -> str:
    """Read a file from the user's vault. Use this when the user references
    a document, note, or configuration file. The path must be relative to
    the vault root. Returns the file contents as a string.

    Args:
        path: Relative path within the vault (e.g., 'notes/project.md')
    """
    ...
```

Dynamic docstrings can inject valid parameter values at runtime (e.g., listing available vault files in the tool description) to reduce hallucinated tool calls [42].

---

## 4. LangChain 1.0 Middleware

LangChain 1.0 introduces a formal middleware architecture with three hooks that operate *inside* the agent's ReAct loop, distinct from graph nodes which operate *around* the loop [47][48].

### 4.1 `before_model`

Runs before each LLM call. Handles conversation summarization, dynamic context injection, and rate limiting:

```python
class ConversationMemoryMiddleware:
    async def before_model(self, state, config):
        if len(state["messages"]) > 50:
            summary = await summarize(state["messages"][:-10])
            state["messages"] = [summary] + state["messages"][-10:]
        return state
```

Replaces prompt instructions like "keep context focused" or "summarize long conversations" [47].

### 4.2 `modify_model_request`

Runs immediately before invocation. Modifies tools, prompts, message lists, and model selection per-request without touching permanent state:

```python
class CostOptimizationMiddleware:
    async def modify_model_request(self, request, config):
        if is_simple_query(request.messages[-1]):
            request.model = "claude-3-haiku"  # Cheaper model
            request.tools = [t for t in request.tools if t.name in BASIC_TOOLS]
        return request
```

Replaces prompt instructions like "use efficient reasoning" with architectural routing [47][48].

### 4.3 `after_model`

Runs after model response. Implements guardrails, content filtering, and human-in-the-loop approval:

```python
class OutputGuardrailMiddleware:
    async def after_model(self, response, config):
        if contains_secrets(response.content):
            response.content = redact_secrets(response.content)
        return response
```

Replaces "never output sensitive data" with code-enforced redaction [47].

### 4.4 When to Use Middleware vs Graph Nodes

- **Middleware**: Deterministic, always-on logic inside the ReAct loop (logging, rate limiting, conversation trimming, output scrubbing). Lightweight and reusable across agents [50].
- **Graph nodes**: Conditional logic that routes between different processing paths (session classification, memory loading). Structural and visible in the graph topology [1].
- **Tool descriptions**: Domain-specific, variable behavior (code review guidelines, file access patterns) [42][43].

---

## 5. NeMo Guardrails

### 5.1 Architecture

NeMo Guardrails (v0.21.0, Apache 2.0) is an intermediary middleware layer between the application and the LLM, intercepting every message through a five-stage pipeline [11][13]:

```
User Input --> [Input Rails] --> [Dialog Rails] --> [Retrieval Rails]
    --> LLM Generation --> [Tool Rails] --> [Output Rails] --> Response
```

The `LLMRails` orchestrator coordinates all stages. Configuration is loaded via `RailsConfig.from_path("./config")` from YAML and Colang files [13].

### 5.2 Output Rails for Secret Detection

Custom Python actions can inspect and block LLM output before it reaches the user [55]:

```python
import re
from nemoguardrails.actions import action

SECRET_PATTERNS = [
    r'(sk-[a-zA-Z0-9]{20,})',           # OpenAI keys
    r'(AKIA[0-9A-Z]{16})',               # AWS access keys
    r'(xoxb-[0-9]{11}-[0-9]{11}-\w+)',   # Slack tokens
    r'(ghp_[a-zA-Z0-9]{36})',            # GitHub PATs
    r'(glpat-[a-zA-Z0-9\-_]{20,})',      # GitLab PATs
    r'(Bearer\s+[a-zA-Z0-9\-_.]+)',      # Bearer tokens
]

@action(is_system_action=True, output_mapping=lambda v: not v)
async def check_output_for_secrets(context: dict = None):
    bot_message = context.get("bot_message", "")
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, bot_message):
            return False  # Triggers block
    return True  # Allow
```

Colang flow integration:

```colang
define flow check secrets
    $is_safe = execute check_output_for_secrets
    if not $is_safe
        bot refuse to share secrets
        stop
```

YAML configuration:

```yaml
rails:
  output:
    flows:
      - check secrets
      - self check output
```

### 5.3 PII Detection Backends

NeMo supports multiple PII backends, configurable per deployment [11][14][18]:

- **GLiNER** (v0.20.0+): NVIDIA's open-source NER model for names, emails, phone numbers, SSNs
- **Microsoft Presidio**: Analyzer + anonymizer pipeline with custom recognizers
- **Guardrails AI**: `guardrails_pii` validator from Guardrails Hub
- **Private AI**: Third-party masking service

### 5.4 LangGraph Integration

`RunnableRails` wraps any LangChain Runnable with guardrails [19]:

```python
from nemoguardrails.integrations.langchain import RunnableRails

guardrails = RunnableRails(config=config, passthrough=True)
guarded_agent = guardrails | agent_runnable
```

Each node in a multi-agent LangGraph system can have its own guardrail configuration. Key limitation: RunnableRails produces single large chunks rather than token-level streaming [19].

In v0.21.0, `GuardrailsMiddleware` provides more seamless integration with LangChain agents [14].

### 5.5 Performance

Overhead: 20-100ms per request [22]. Optimizations in v0.21.0:

- Parallel rail execution (IORails engine)
- Single-call dialog mode (one LLM call for intent + steps + message)
- Lazy embedding index initialization
- In-memory LFU caching (v0.18.0)
- Streaming: configurable `chunk_size` (200-256 tokens) with `stream_first: True` for low-latency delivery [23]

**Caveat**: Streaming with `stream_first` may deliver objectionable tokens before the output rail catches them [23].

### 5.6 Deployment

Entirely self-hosted. Three deployment modes [11][13]:

```bash
# Embedded in application
rails = LLMRails(RailsConfig.from_path("./config"))
response = await rails.generate_async(messages=messages)

# Standalone FastAPI server (OpenAI-compatible)
nemoguardrails server --config ./config --port 8000

# Docker
docker run -p 8000:8000 -v ./config:/config nemoguardrails:latest
```

---

## 6. Code-Based Guardrails

### 6.1 Credential Detection

**Guardrails AI `SecretsPresent`**: Wraps `detect-secrets` with entropy-based detection and regex patterns for 30+ key formats (AWS, Slack, Stripe, GitHub, GitLab, etc.). Three failure modes: `exception` (halt), `fix` (redact with asterisks), `reask` (re-prompt LLM) [29].

```python
from guardrails import Guard
from guardrails.hub import SecretsPresent

guard = Guard().use(SecretsPresent(on_fail="exception"))
guard.validate(llm_output_text)  # Raises on detection
```

**LLM Guard** (Protect AI): 15 input scanners + 20 output scanners, including `Secrets` and `Sensitive`. Sequential scanning pipeline [30].

### 6.2 Bash Command Blocking (AST-Based)

Regex-based command blocking is fragile -- it misses shell quoting, escaping, and obfuscation. The `bashlex` library provides AST-based parsing [33]:

```
User command: sudo env rm -rf /
                |     |    |
                v     v    v
        WrapperCheck  EnvCheck  BlacklistCheck
              BLOCKED: wrapper bypass attempt
```

Five sequential security checks in the claude-code-bash-guardian pattern [33]:

1. **EnvironmentVariableCheck**: Blocks `LD_PRELOAD`, `PATH` overrides
2. **PipeSecurityCheck**: Blocks piping to `sh`/`bash`
3. **VariableCommandCheck**: Blocks `$var` as command names
4. **BlacklistCheck**: Pattern-matched command blocklist
5. **PathAccessCheck**: Restricts filesystem to project directory + `/tmp`

Wrapper-command detection catches `sudo`, `xargs`, `env`, `timeout` used to execute blocked commands indirectly [33].

### 6.3 PII Scrubbing with Presidio

Microsoft Presidio separates identification (`AnalyzerEngine`) from de-identification (`AnonymizerEngine`) [36][37]:

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
results = analyzer.analyze(
    text=llm_output,
    entities=["PHONE_NUMBER", "CREDIT_CARD", "EMAIL_ADDRESS",
              "US_SSN", "PERSON"],
    language="en"
)

anonymizer = AnonymizerEngine()
anonymized = anonymizer.anonymize(text=llm_output, analyzer_results=results)
```

Custom recognizers for domain-specific patterns (internal employee IDs, vault encryption keys):

```python
from presidio_analyzer import PatternRecognizer, Pattern

vault_key_recognizer = PatternRecognizer(
    supported_entity="VAULT_KEY",
    patterns=[Pattern("vault_key", r"vk-[a-f0-9]{64}", 0.9)]
)
analyzer.registry.add_recognizer(vault_key_recognizer)
```

Presidio explicitly acknowledges it is "one layer in defense-in-depth" -- not all PII will be caught [36].

### 6.4 Reversible Anonymization

The entity map pattern enables PII-safe LLM processing with restoration [38]:

```python
entity_map = {}
counter = {"EMAIL": 0, "PHONE": 0}

def anonymize(text: str) -> tuple[str, dict]:
    for entity_type, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text):
            counter[entity_type] += 1
            placeholder = f"[{entity_type}_{counter[entity_type]}]"
            entity_map[placeholder] = match.group()
            text = text.replace(match.group(), placeholder)
    return text, entity_map

def restore(text: str, entity_map: dict) -> str:
    for placeholder, original in entity_map.items():
        text = text.replace(placeholder, original)
    return text
```

The LLM sees `[EMAIL_1]` instead of `alice@example.com`. Client-side restoration happens after output guardrails pass [38].

### 6.5 The Bidirectional Scanning Gap

Most implementations only scrub inputs. But LLMs can hallucinate PII in output -- generating plausible email addresses, phone numbers, or credentials that were never in the input [39]. Production systems must scan both directions.

### 6.6 High-Performance Detection with Rust

The `llm-guardrails` library implements core regex in Rust via PyO3, providing compiled patterns with zero-copy processing and C-level performance [56]. This matters for high-throughput deployments where Python regex becomes a bottleneck.

---

## 7. Memory Architecture

### 7.1 Short-Term Memory: Checkpointer + Thread ID

Each conversation session gets a unique `thread_id`. The checkpointer stores state snapshots at every superstep, enabling resume, time-travel debugging, and human-in-the-loop [52][53]:

```python
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

pool = ConnectionPool(conninfo=DB_URI, max_size=10)
with pool.connection() as conn:
    saver = PostgresSaver(conn)
    saver.setup()

graph = builder.compile(checkpointer=saver)
```

Thread ID pattern for CommandClaw: `"user-{user_id}:session-{session_uuid}"`.

**Backend selection** [54]:

| Backend | Use Case | Persistence | Concurrency |
|---|---|---|---|
| InMemorySaver | Development | None | Single-process |
| SqliteSaver | Local/testing | File-based | Single-process |
| PostgresSaver | Production | Durable | Connection pool |
| RedisSaver | High-throughput | In-memory + AOF | Native async |

All require `checkpointer.setup()` on first use [54].

### 7.2 Long-Term Memory: Store API

Cross-thread memory uses the Store API with tuple-based namespaces [5][52]:

```
+-----------------------+     +---------------------------+
| Thread 1 (session A)  |     | Store                     |
| checkpointer state    |---->| ("shikhar","preferences") |
+-----------------------+     | ("shikhar","vault_index") |
                              | ("system","instructions") |
+-----------------------+     +---------------------------+
| Thread 2 (session B)  |            ^
| checkpointer state    |------------+
+-----------------------+
```

The `load_memory` pre-processing node reads from the Store before the agent runs. The agent can also write to the Store during execution (e.g., learning a new preference from conversation).

### 7.3 Vault Files as On-Demand Context

Vault files (markdown, YAML, code) are not loaded into the Store wholesale. Instead, a vault index is maintained in the Store, and files are loaded on-demand by the `read_vault_file` tool:

```python
async def load_memory(state, runtime):
    # Load vault index (lightweight)
    vault_idx = await runtime.store.asearch(
        (runtime.context.user_id, "vault_index"), query="*"
    )
    # Load user preferences (always)
    prefs = await runtime.store.asearch(
        (runtime.context.user_id, "preferences"), query="current"
    )
    return {
        "vault_context": [f"Available vault files: {[i.key for i in vault_idx]}"],
        "memory_loaded": True,
    }
```

The agent sees available file names but does not load file contents until explicitly requested via tool call. This avoids bloating context with irrelevant vault data.

---

## 8. Heartbeats and Scheduled Tasks

### 8.1 LangGraph Platform Cron Jobs

The LangGraph Platform provides first-class cron scheduling [7][9]:

```python
from langgraph_sdk import get_client

client = get_client()

# Stateful cron: reuses thread (ideal for heartbeats)
cron = await client.crons.create_for_thread(
    thread_id="user-shikhar:session-abc",
    assistant_id="commandclaw",
    schedule="*/10 * * * *",  # Every 10 minutes
    input={"messages": [{"role": "user", "content": "heartbeat"}],
           "trigger_source": "scheduler"}
)

# Stateless cron: new thread each run (cleanup tasks)
cleanup = await client.crons.create(
    assistant_id="commandclaw",
    schedule="0 0 * * *",  # Daily at midnight
    input={"messages": [{"role": "user", "content": "daily cleanup"}],
           "trigger_source": "scheduler"},
    on_run_completed="delete"
)
```

Cron jobs run in the background. All schedules are UTC. API: `create()`, `create_for_thread()`, `update()`, `delete()`, `search()`, `count()` [9].

### 8.2 Heartbeat Routing

The graph detects scheduler-triggered invocations via the `trigger_source` state field and routes to a dedicated heartbeat handler:

```python
def route_by_trigger(state: CommandClawState) -> str:
    if state["trigger_source"] == "scheduler":
        return "heartbeat_handler"
    return "load_memory"

async def heartbeat_handler(state: CommandClawState, runtime):
    # Check session health, update metrics, send status
    health = await check_session_health(state)
    if health["stale"]:
        await notify_user(runtime.context.user_id, "Session idle")
    return {"heartbeat_due": False}
```

### 8.3 Event-Driven Triggers

Beyond cron, LangGraph supports [10]:

- **Event-based**: Completion signals from other agents
- **State-based**: Conditional edges evaluating current state
- **External**: Webhooks (FastAPI endpoints), API calls, message queues

```python
# Webhook trigger via FastAPI
@app.post("/webhook/vault-update")
async def vault_update_webhook(payload: dict):
    await graph.ainvoke(
        {"messages": [{"role": "system", "content": f"Vault updated: {payload}"}],
         "trigger_source": "webhook"},
        config={"configurable": {"thread_id": payload["thread_id"]}}
    )
```

---

## 9. Proposed CommandClaw Refactor: Concrete Architecture

### 9.1 The New Graph

```
                         START
                           |
                    route_by_trigger()
                    /              \
                   v                v
          load_memory()      heartbeat_handler()-->END
                   |
          classify_session()
                   |
          route_after_classify()
          /        |          \
         v         v           v
   coding_agent  research_   general_
                  agent       agent
         \         |          /
          v        v         v
         output_guardrails()
                   |
            route_guardrail_result()
               /          \
              v            v
            END      block_and_notify()-->END
```

### 9.2 Node-to-Prompt Replacement Map

| Node | Replaces prompt instruction | Implementation |
|---|---|---|
| `route_by_trigger` | N/A (new capability) | Conditional edge from START |
| `load_memory` | "Load user memory files at conversation start" | Store API reads with context schema |
| `classify_session` | "Detect session type from first message" | LLM call or rule-based classifier |
| `route_after_classify` | "If coding session, use tools X/Y" | Conditional edge, pure Python |
| `coding_agent` | Tool routing embedded in prompt | Subgraph with coding-specific tools |
| `output_guardrails` | "Never output API keys or PII" | NeMo output rail or custom action |
| `block_and_notify` | N/A (currently silent failure) | Explicit user notification on block |

### 9.3 Middleware Stack

```python
agent = create_agent(
    model=ChatAnthropic(model="claude-sonnet-4-20250514"),
    tools=tools,
    middleware=[
        ConversationMemoryMiddleware(),     # before_model: trim/summarize
        CostOptimizationMiddleware(),       # modify_model_request: model routing
        OutputGuardrailMiddleware(),         # after_model: secret/PII scrub
        ToolFilterMiddleware(),             # modify_model_request: dynamic tools
    ],
    system_prompt="You are CommandClaw, a senior software engineering agent. "
                  "Use your tools to accomplish tasks. Be direct and concise."
)
```

### 9.4 Guardrail Attachment Points

```
                    +------------------+
                    |  Input           |
                    |  - Jailbreak     |  <-- NeMo input rail OR custom
                    |  - PII mask      |  <-- Presidio pre-process
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Tool Execution  |
                    |  - Bash blocklist|  <-- bashlex AST check
                    |  - Path restrict |  <-- PathAccessCheck
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Output          |
                    |  - Secret scan   |  <-- detect-secrets / regex
                    |  - PII scrub     |  <-- Presidio post-process
                    |  - Content safety|  <-- NeMo output rail
                    +------------------+
```

### 9.5 State Schema

```python
class CommandClawState(TypedDict):
    # Core conversation
    messages: Annotated[list, add_messages]

    # Session management
    session_type: Literal["coding", "research", "general"]
    trigger_source: Literal["user", "scheduler", "webhook"]
    user_id: str

    # Memory
    memory_loaded: bool
    vault_context: list[str]
    loaded_preferences: list[dict]

    # Guardrails
    guardrail_violations: Annotated[list[str], operator.add]

    # Heartbeat
    heartbeat_due: bool
    last_heartbeat: float  # Unix timestamp


@dataclass
class CommandClawContext:
    user_id: str
    vault_path: str = "/apps/commandclaw-vault"
    llm_provider: str = "anthropic"
```

---

## 10. Recommendations

### 10.1 NeMo Guardrails vs Custom Guardrails

| Criterion | NeMo Guardrails | Custom Code |
|---|---|---|
| Setup complexity | High (Colang, YAML config, event model) | Low (Python functions) |
| PII detection | Multiple backends (GLiNER, Presidio) | Presidio or regex directly |
| Secret detection | Custom action required | Direct regex or detect-secrets |
| Bash command blocking | Not supported | bashlex AST parsing |
| Performance | 20-100ms overhead | <5ms for regex, variable for ML |
| Streaming | Chunk-based, may leak content | Full control |
| Maintainability | Configuration-driven, declarative | Code-driven, imperative |
| Team familiarity | Requires Colang learning curve | Standard Python |

**Recommendation**: Start with custom code-based guardrails for the initial refactor. NeMo adds complexity (Colang, YAML, event model) without proportional benefit for CommandClaw's current needs. The primary guardrail requirements -- secret detection, bash blocking, PII scrubbing -- are well-served by `detect-secrets` + `bashlex` + Presidio. Revisit NeMo if content safety classification (jailbreak detection, topic restriction) becomes a requirement, where its Nemotron-Content-Safety-Reasoning-4B model provides real value [21].

### 10.2 Middleware vs Graph Nodes

**Use middleware for**:
- Conversation memory management (summarization, trimming)
- Per-request model/tool selection
- Output scrubbing (secrets, PII)
- Logging and observability

**Use graph nodes for**:
- Session classification and routing
- Memory loading from Store
- Heartbeat handling
- Vault context injection

**Use tool descriptions for**:
- Domain-specific behavior (code review, file access patterns)
- Tool selection guidance
- Parameter validation documentation

### 10.3 Migration Path

**Phase 1: Graph skeleton** (1-2 weeks)
- Implement `CommandClawState` and `CommandClawContext`
- Build `load_memory` -> `classify_session` -> agent pipeline
- Replace session detection prompt logic with `classify_session` node
- Compile with PostgresSaver checkpointer
- Keep existing system prompt temporarily as fallback

**Phase 2: Guardrails** (1-2 weeks)
- Implement `OutputGuardrailMiddleware` with `detect-secrets` for secret scanning
- Add bashlex-based PreToolUse command blocking
- Add Presidio PII scrubbing as `after_model` middleware
- Remove guardrail instructions from system prompt

**Phase 3: Memory refactor** (1 week)
- Migrate user preferences to Store API
- Implement vault index in Store
- Convert vault file loading to on-demand tool calls
- Remove memory loading instructions from system prompt

**Phase 4: Heartbeats and cron** (1 week)
- Set up LangGraph Platform cron for heartbeats
- Implement `heartbeat_handler` node
- Add `route_by_trigger` conditional entry point
- Remove heartbeat instructions from system prompt

**Phase 5: Prompt minimization** (1 week)
- Reduce system prompt to ~50 tokens (identity + meta-instruction)
- Ensure all tool descriptions are self-documenting
- Validate with integration tests covering all previous prompt behaviors
- Monitor token consumption reduction

---

## Conclusion

The refactor from prompt-based to code-structural agent behavior is not merely an optimization -- it is an architectural shift from probabilistic behavioral compliance to deterministic enforcement. LangGraph's StateGraph provides the runtime backbone: typed state schemas replace prompt-injected session metadata, conditional edges replace LLM-interpreted routing instructions, pre-processing nodes guarantee memory loading before agent execution, and cron jobs replace prompt-instructed heartbeats. LangChain 1.0 middleware fills the gap for always-on logic inside the ReAct loop (conversation trimming, output scrubbing, model routing), while tool descriptions carry domain-specific behavioral contracts.

For guardrails, the research supports a custom code approach over NeMo Guardrails for CommandClaw's current needs. The combination of `detect-secrets` (credential scanning), `bashlex` (AST-based command blocking), and Presidio (PII detection) provides deterministic enforcement with sub-5ms overhead and no new DSL to learn. NeMo becomes relevant when content safety classification or multi-agent guardrail orchestration is needed.

The expected outcome: a ~75-90% reduction in per-request token consumption [42], deterministic guardrail enforcement (no more "the model forgot the rule"), testable behavior via synthetic state injection, and observable agent control flow via graph visualization and checkpoint inspection.

---

## References

See [agent-logic-refactor-references.md](agent-logic-refactor-references.md) for the full bibliography.
In-text citations use bracketed IDs, e.g., [1], [2].
