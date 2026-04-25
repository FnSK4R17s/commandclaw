# Crazy ideas — message-queue feature

Future directions that are out of scope for v1 but worth revisiting.

- **External message broker** (Redis Streams, RabbitMQ) — durable queues that survive process restarts, enable horizontal scaling across multiple bot instances
- **Sub-agent orchestration queue** — parent agent dispatches tasks to child agents via the queue, collects results, coordinates timeouts
- **Agent team communication MQ** — multiple agents communicate peer-to-peer through named channels, pub/sub topics, or shared mailboxes
- **Streaming token delivery** — stream LLM tokens to Telegram as they arrive instead of waiting for the full response
