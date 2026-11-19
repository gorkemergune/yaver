//! Talks to the Yaver backend. Requests go out from Rust, not from the webview: the API
//! sends no CORS headers and the webview's origin (`http://tauri.localhost`) is foreign.

use serde::Serialize;
use serde_json::{json, Value};
use std::time::Duration;

pub const DEFAULT_API_URL: &str = "http://localhost:8080";
/// Overrides the saved address (handy for a second instance or a Tailscale host).
pub const API_URL_ENV: &str = "YAVER_API_URL";

/// A chat turn can take several LLM calls (delegation, tools, failover).
const CHAT_TIMEOUT: Duration = Duration::from_secs(300);
const SHORT_TIMEOUT: Duration = Duration::from_secs(15);

/// Error shape the frontend turns into a Turkish message.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ApiError {
    /// `invalid_url` | `unreachable` | `timeout` | `http` | `bad_response`
    pub code: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

impl ApiError {
    fn new(code: &'static str) -> Self {
        Self {
            code,
            status: None,
            detail: None,
        }
    }
}

impl From<reqwest::Error> for ApiError {
    fn from(err: reqwest::Error) -> Self {
        let code = if err.is_timeout() {
            "timeout"
        } else if err.is_connect() || err.is_request() {
            "unreachable"
        } else {
            "bad_response"
        };
        Self {
            detail: Some(err.to_string()),
            ..Self::new(code)
        }
    }
}

/// `localhost:8080/` → `http://localhost:8080`; a pasted `.../api` suffix is dropped
/// because every path below already starts with `/api`.
pub fn normalize_api_url(raw: &str) -> Result<String, ApiError> {
    let trimmed = raw.trim();
    let with_scheme = if trimmed.contains("://") {
        trimmed.to_owned()
    } else {
        format!("http://{trimmed}")
    };
    let url = reqwest::Url::parse(&with_scheme).map_err(|_| ApiError::new("invalid_url"))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none_or(str::is_empty) {
        return Err(ApiError::new("invalid_url"));
    }
    let mut text = url.as_str().trim_end_matches('/').to_owned();
    if let Some(stripped) = text.strip_suffix("/api") {
        text = stripped.to_owned();
    }
    Ok(text)
}

pub struct Client {
    http: reqwest::Client,
}

impl Client {
    pub fn new() -> Self {
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(5))
            .build()
            .expect("HTTP client");
        Self { http }
    }

    async fn send(
        &self,
        request: reqwest::RequestBuilder,
        timeout: Duration,
    ) -> Result<Value, ApiError> {
        let response = request.timeout(timeout).send().await?;
        let status = response.status();
        let text = response.text().await?;
        if !status.is_success() {
            return Err(ApiError {
                status: Some(status.as_u16()),
                detail: error_detail(&text),
                ..ApiError::new("http")
            });
        }
        serde_json::from_str(&text).map_err(|err| ApiError {
            detail: Some(err.to_string()),
            ..ApiError::new("bad_response")
        })
    }

    /// `POST /api/chat` (non-streaming): the whole reply at once.
    pub async fn chat(
        &self,
        base: &str,
        message: &str,
        conversation_id: Option<i64>,
    ) -> Result<Value, ApiError> {
        let body = json!({ "message": message, "conversation_id": conversation_id });
        let request = self.http.post(format!("{base}/api/chat")).json(&body);
        self.send(request, CHAT_TIMEOUT).await
    }

    /// `POST /api/changes/{id}/undo`: the "Geri al" button, no LLM involved.
    pub async fn undo(&self, base: &str, change_set_id: &str) -> Result<Value, ApiError> {
        if uuid_like(change_set_id) {
            let request = self
                .http
                .post(format!("{base}/api/changes/{change_set_id}/undo"));
            self.send(request, SHORT_TIMEOUT).await
        } else {
            Err(ApiError::new("bad_response"))
        }
    }

    /// `GET /api/team`: names and label colors; also the "is the server there?" check.
    pub async fn team(&self, base: &str) -> Result<Value, ApiError> {
        let request = self.http.get(format!("{base}/api/team"));
        self.send(request, SHORT_TIMEOUT).await
    }
}

/// FastAPI errors look like `{"detail": "..."}` or `{"detail": {"message": "..."}}`.
fn error_detail(body: &str) -> Option<String> {
    let value: Value = serde_json::from_str(body).ok()?;
    let detail = value.get("detail")?;
    match detail {
        Value::String(text) => Some(text.clone()),
        Value::Object(map) => map
            .get("message")
            .and_then(Value::as_str)
            .map(str::to_owned),
        other => Some(other.to_string()),
    }
}

/// Keeps the id from smuggling extra path segments into the URL.
fn uuid_like(id: &str) -> bool {
    !id.is_empty() && id.len() <= 64 && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_api_urls() {
        let ok = |raw: &str| normalize_api_url(raw).unwrap();
        assert_eq!(ok("http://localhost:8080"), "http://localhost:8080");
        assert_eq!(ok(" http://localhost:8080/ "), "http://localhost:8080");
        assert_eq!(ok("localhost:8080"), "http://localhost:8080");
        assert_eq!(
            ok("http://pc.tail1234.ts.net:8080/api/"),
            "http://pc.tail1234.ts.net:8080"
        );
        assert_eq!(ok("https://yaver.example.com"), "https://yaver.example.com");
        assert_eq!(
            ok("http://192.168.1.20:8080/yaver"),
            "http://192.168.1.20:8080/yaver"
        );
    }

    #[test]
    fn rejects_bad_api_urls() {
        for raw in ["", "   ", "ftp://host", "http://", "file:///C:/x"] {
            assert_eq!(
                normalize_api_url(raw).unwrap_err().code,
                "invalid_url",
                "{raw:?}"
            );
        }
    }

    #[test]
    fn reads_fastapi_error_details() {
        assert_eq!(
            error_detail(r#"{"detail": "nothing to undo"}"#).as_deref(),
            Some("nothing to undo")
        );
        assert_eq!(
            error_detail(r#"{"detail": {"code": "bad_attachments", "message": "gone"}}"#)
                .as_deref(),
            Some("gone")
        );
        assert_eq!(error_detail("<html>502</html>"), None);
    }

    #[test]
    fn change_set_ids_are_checked() {
        assert!(uuid_like("3f2b8c1e-0d4a-4c7e-9a51-2b6f0e9d1c33"));
        assert!(!uuid_like("../../health"));
        assert!(!uuid_like(""));
    }
}
