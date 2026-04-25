# NeMo Guardrails Self-Check Rails — Research Questions

<!-- Research questions for the nemo-guardrails-self-check topic. -->

## General Understanding

### Q1: What is the NeMo Guardrails v0.21 self_check_input and self_check_output rail architecture — what built-in flows, actions, and prompts are involved?

**Search terms:**
- NeMo Guardrails self_check_input self_check_output built-in flow v0.21 site:github.com/NVIDIA/NeMo-Guardrails
- NeMo Guardrails output_parser is_content_safe default parser registration
- NVIDIA NeMo Guardrails v0.21 input output rails configuration prompts.yml

### Q2: How does the output_parser work for self_check tasks — what is is_content_safe, what response format does it expect, and how is it registered?

**Search terms:**
- NeMo Guardrails output_parser task registration is_content_safe
- NeMo Guardrails "output parser is not registered" self_check
- NeMo Guardrails v0.21 prompts.yml output_parser field format

### Q3: What does generate_async return when a self_check rail blocks a request, and what does the response dict look like?

**Search terms:**
- NeMo Guardrails generate_async return value blocked input rail
- NeMo Guardrails "bot refuse" response dict structure
- NeMo Guardrails v0.21 generate response format when rail fires

### Q4: Where should prompts be defined — in config.yml, a separate prompts.yml, or elsewhere — and what are the exact required fields for self_check_input/self_check_output tasks?

**Search terms:**
- NeMo Guardrails prompts.yml vs config.yml prompt configuration self_check
- NeMo Guardrails example config self_check_input task type prompt models
- site:github.com NVIDIA/NeMo-Guardrails examples self_check_input config

---

## Deeper Dive

### Subtopic 1: output_parser configuration and is_content_safe behavior

#### Q1: What is the exact output_parser field value needed for self_check_input and self_check_output tasks, and where in config.yml or prompts.yml is it placed?

**Search terms:**
- NeMo Guardrails "output_parser" "self_check_input" config example
- NeMo Guardrails is_content_safe parser "safe" "unsafe" response format
- NeMo Guardrails v0.21 prompts task self_check output_parser field

#### Q2: Does is_content_safe look for the word "safe" or "yes" or something else in the LLM response, and what prompt phrasing drives correct behavior?

**Search terms:**
- NeMo Guardrails is_content_safe implementation source code parser logic
- NeMo Guardrails self_check_input prompt "Answer: Yes/No" vs "safe/unsafe"
- NVIDIA NeMo Guardrails content safety parser response format

#### Q3: What are known pitfalls or bugs in NeMo Guardrails self_check rails that cause false positives, false negatives, or the output parser warning?

**Search terms:**
- NeMo Guardrails self_check false positive rails not blocking
- NeMo Guardrails "output parser" warning self_check fix
- NeMo Guardrails v0.21 issues self_check_input blocked all messages

### Subtopic 2: generate_async response structure and prompts file layout

#### Q1: What does the generate_async/generate method return when input is blocked vs allowed — exact dict schema?

**Search terms:**
- NeMo Guardrails generate_async response structure blocked input dict
- NeMo Guardrails RailsConfig generate response format "bot refuse"
- NeMo Guardrails v0.21 API response when input rail fires

#### Q2: What is the complete correct structure of prompts.yml for self_check_input and self_check_output including all required fields?

**Search terms:**
- NeMo Guardrails prompts.yml complete example self_check_input self_check_output
- site:github.com NVIDIA/NeMo-Guardrails prompts.yml models task type
- NeMo Guardrails v0.21 documentation prompts configuration file structure

---

## Redundant Questions

<!-- None yet -->
