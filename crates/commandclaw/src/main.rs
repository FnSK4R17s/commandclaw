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
//! S1 (this file): Telegram echo — proves the channel. Next is S2, the agent
//! loop (hand-written), which replaces the echo with a real model call.

use std::collections::HashSet;

use teloxide::prelude::*;

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();

    let allowed = parse_allowed_chats();
    let bot = Bot::from_env();
    println!(
        "commandclaw S1: telegram echo online ({} allow-listed chat(s); 0 = open). Message the bot.",
        allowed.len()
    );

    teloxide::repl(bot, move |bot: Bot, msg: Message| {
        let allowed = allowed.clone();
        async move {
            // S1 boundary: ignore anyone not allow-listed (empty list = allow all).
            if !allowed.is_empty() && !allowed.contains(&msg.chat.id.0) {
                return Ok(());
            }
            if let Some(text) = msg.text() {
                bot.send_message(msg.chat.id, text).await?;
            }
            Ok(())
        }
    })
    .await;
}

/// Parse `COMMANDCLAW_ALLOWED_CHAT_IDS` (comma-separated chat ids). Empty/unset = allow all.
fn parse_allowed_chats() -> HashSet<i64> {
    std::env::var("COMMANDCLAW_ALLOWED_CHAT_IDS")
        .unwrap_or_default()
        .split(',')
        .filter_map(|s| s.trim().parse::<i64>().ok())
        .collect()
}
