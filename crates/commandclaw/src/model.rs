//! S2 table — a minimal OpenAI-compatible model client the agent loop calls.
//! This is plumbing (mine). The loop that *uses* it is yours (see `respond` in main.rs).

use anyhow::Result;
use async_openai::{
    Client,
    config::OpenAIConfig,
    types::chat::{ChatCompletionRequestUserMessageArgs, CreateChatCompletionRequestArgs},
};

/// Thin wrapper over an OpenAI-compatible chat endpoint.
pub struct ModelClient {
    client: Client<OpenAIConfig>,
    model: String,
}

impl ModelClient {
    /// Build from env:
    /// - `OPENAI_API_KEY` (required; read by `OpenAIConfig`),
    /// - `OPENAI_BASE_URL` (optional — point at any OpenAI-compatible provider),
    /// - `COMMANDCLAW_MODEL` (default `gpt-4o-mini`).
    pub fn from_env() -> Self {
        let mut config = OpenAIConfig::new();
        if let Ok(base) = std::env::var("OPENAI_BASE_URL") {
            config = config.with_api_base(base);
        }
        let model =
            std::env::var("COMMANDCLAW_MODEL").unwrap_or_else(|_| "gpt-4o-mini".to_string());
        Self {
            client: Client::with_config(config),
            model,
        }
    }

    /// Single-turn completion. The agent loop grows from here (history, tools, spec authoring).
    pub async fn chat(&self, user: &str) -> Result<String> {
        let request = CreateChatCompletionRequestArgs::default()
            .model(&self.model)
            .messages([ChatCompletionRequestUserMessageArgs::default()
                .content(user)
                .build()?
                .into()])
            .build()?;
        let response = self.client.chat().create(request).await?;
        Ok(response
            .choices
            .into_iter()
            .next()
            .and_then(|choice| choice.message.content)
            .unwrap_or_default())
    }
}
