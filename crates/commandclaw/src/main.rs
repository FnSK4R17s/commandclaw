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
//! This is S0: the scaffold. Subsequent steps add crates:
//!   S1 telegram channel, S2 model layer, S5/S6 the MCP seam to ckrv-mcp.

use anyhow::Result;

#[tokio::main]
async fn main() -> Result<()> {
    println!(
        "commandclaw: S0 scaffold green. \
         M1 = the delegation slice — see plan/M1-delegation-slice.md."
    );
    Ok(())
}
