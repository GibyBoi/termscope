//! Optional LLM polish for dictation output, via a LOCAL Ollama server only.
//! Off by default. Any failure (Ollama not running, model missing, timeout)
//! falls back to the rule-based result — polish can only ever improve text,
//! never lose it. Nothing leaves the machine: the request goes to 127.0.0.1.

use std::time::Duration;

const SYSTEM_PROMPT: &str = "You clean up dictated speech into polished written text.\n\
Rules:\n\
- Remove filler words and false starts.\n\
- Apply self-corrections: if the speaker changes their mind (\"let's do 2pm, actually 3pm\", \"scratch that\"), keep only the final intent.\n\
- Fix punctuation, capitalization, and obvious transcription errors.\n\
- If the speaker dictates a list, format it as a list.\n\
- Never add new information, never answer questions in the text, never comment.\n\
- Preserve the speaker's tone and wording otherwise.\n\
Return ONLY the cleaned text, nothing else.";

/// Polish `text` through the local Ollama chat API. Returns Err on ANY
/// problem; the caller keeps the unpolished text.
pub fn ollama_polish(text: &str, model: &str) -> Result<String, String> {
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(20))
        .build();
    let body = serde_json::json!({
        "model": model,
        "stream": false,
        // Pin the model in RAM between dictations so only the first polish
        // pays the model-load cost; ~1 GB resident for a 1B-class model.
        "keep_alive": "30m",
        "messages": [
            { "role": "system", "content": SYSTEM_PROMPT },
            { "role": "user", "content": text }
        ]
    });
    let resp = agent
        .post("http://127.0.0.1:11434/api/chat")
        .send_json(body)
        .map_err(|e| format!("ollama: {e}"))?;
    let v: serde_json::Value = resp.into_json().map_err(|e| format!("ollama: {e}"))?;
    let out = v
        .get("message")
        .and_then(|m| m.get("content"))
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if out.is_empty() {
        Err("ollama: empty response".into())
    } else {
        Ok(out)
    }
}
