# Agent Logic Refactor — Research Questions

## General Understanding

### Q1: How does LangGraph implement agent state management, conditional routing, and scheduled tasks — and how can these replace prompt-based instructions for things like heartbeats, session type detection, and memory loading?

**Search terms:**
- LangGraph conditional edges state management agent routing Python 2025
- LangGraph scheduled tasks background jobs periodic execution
- LangGraph agent state machine session management conversation memory

### Q2: What is NVIDIA NeMo Guardrails, how does it work architecturally, and what guardrail patterns does it provide for output filtering, PII detection, and tool call validation?

**Search terms:**
- NeMo Guardrails architecture Colang output rails PII detection 2025
- NeMo Guardrails LangChain integration Python programmable guardrails
- NeMo Guardrails input output filtering content moderation LLM agents

### Q3: How do production LLM agent frameworks implement guardrails in code rather than prompts — specifically for credential leak prevention, dangerous command blocking, and output sanitization?

**Search terms:**
- LLM agent guardrails code implementation credential leak prevention Python
- LangChain output parser guardrails dangerous command blocking
- LLM agent output sanitization PII scrubbing before response delivery

### Q4: What are the best practices for minimal system prompts in LangGraph agents, and how do teams move behavior from prompts into graph nodes, edges, and tool logic?

**Search terms:**
- LangGraph minimal system prompt agent design best practices
- moving agent behavior from prompts to code LangGraph nodes
- LangGraph tool node pre-processing post-processing middleware pattern

---

## Deeper Dive

### Subtopic 1: LangGraph Runtime Patterns

#### Q5: How do you implement pre-invocation hooks in LangGraph (read files before agent runs, inject context conditionally, detect session type)?

**Search terms:**
- LangGraph pre-processing node before agent call conditional context injection
- LangGraph graph node before tools after tools middleware Python
- LangGraph StateGraph conditional entry point session routing

#### Q6: How does LangGraph checkpoint/memory work with conversation history, and how do you scope memory per-session vs per-agent?

**Search terms:**
- LangGraph checkpointer thread_id conversation history scoping
- LangGraph MemorySaver SqliteSaver per-user per-session memory
- LangGraph long-term memory short-term memory agent architecture

### Subtopic 2: Guardrails Implementation

#### Q7: How do you implement output guardrails that catch API keys, PII, and sensitive vault content before it reaches the user — using NeMo Guardrails or custom code?

**Search terms:**
- NeMo Guardrails output rail custom action API key detection
- LLM output guardrails regex PII detection Python implementation
- agent output filtering sensitive data prevention before response

---

## Redundant Questions

