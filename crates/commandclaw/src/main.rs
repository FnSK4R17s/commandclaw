//! CommandClaw — the agentic layer. Greenfield Rust rebuild.
//!
//! See `docs/adr/0001` (Rust rebuild + thin MCP seam to CKRV) and
//! `docs/adr/0002` (M1 = the delegation slice). Build plan in
//! `plan/M1-delegation-slice.md`.
//!
//! M1 target round-trip:
//!   Telegram -> agent loop -> author a Spec -> delegate to CKRV over MCP
//!   -> CKRV `spec -> verified diff` -> PR link back to the same chat.
//!
//! S2 (now): the table is set — a working `ModelClient`. The agent loop in
//! `respond()` is YOURS to grow.

mod model;

use std::collections::HashSet;
use std::sync::Arc;

use model::ModelClient;
use teloxide::prelude::*;

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();

    let allowed = parse_allowed_chats();
    let model = Arc::new(ModelClient::from_env());
    let bot = Bot::from_env();
    println!(
        "commandclaw S2: online ({} allow-listed chat(s); 0 = open). Message the bot.",
        allowed.len()
    );

    teloxide::repl(bot, move |bot: Bot, msg: Message| {
        let allowed = allowed.clone();
        let model = model.clone();
        async move {
            if !allowed.is_empty() && !allowed.contains(&msg.chat.id.0) {
                return Ok(());
            }
            if let Some(text) = msg.text() {
                let reply = respond(&model, text).await;
                bot.send_message(msg.chat.id, reply).await?;
            }
            Ok(())
        }
    })
    .await;
}

// ============================================================================
// S2 — THE AGENT LOOP LIVES HERE. THIS IS YOURS.
//
// Right now it's a single-turn model call — the table is set: `model.chat`
// works against whatever OPENAI_API_KEY / OPENAI_BASE_URL / COMMANDCLAW_MODEL
// you put in `.env`. Grow it into the real agentic loop:
//   - keep conversation history per chat,
//   - let the model decide: is this a coding task?
//   - if yes, author a CKRV Spec and delegate over MCP (S4/S6); else just answer.
// Replace / extend the body below.
// ============================================================================
async fn respond(model: &ModelClient, text: &str) -> String {
    match model.chat(text).await {
        Ok(reply) => reply,
        Err(err) => format!("model error: {err}"),
    }
}

/// Parse `COMMANDCLAW_ALLOWED_CHAT_IDS` (comma-separated chat ids). Empty/unset = allow all.
fn parse_allowed_chats() -> HashSet<i64> {
    std::env::var("COMMANDCLAW_ALLOWED_CHAT_IDS")
        .unwrap_or_default()
        .split(',')
        .filter_map(|s| s.trim().parse::<i64>().ok())
        .collect()
}
