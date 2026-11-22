//! Talks to the Yaver backend. Requests go out from Rust, not from the webview: the API
//! sends no CORS headers and the webview's origin (`http://tauri.localhost`) is foreign.

use serde::Serialize;
use serde_json::{json, Value};
use std::sync::RwLock;
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
    /// `invalid_url` | `unreachable` | `timeout` | `http` | `bad_response` |
    /// `login_required` | `wrong_password` | `too_many_attempts` | `invalid_key` |
    /// `device_key_invalid`
    pub code: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

impl ApiError {
    pub fn new(code: &'static str) -> Self {
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
    /// Bearer token from `POST /api/auth/login` (servers with `APP_PASSWORD`).
    token: RwLock<Option<String>>,
}

impl Client {
    pub fn new(token: Option<String>) -> Self {
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(5))
            .build()
            .expect("HTTP client");
        Self {
            http,
            token: RwLock::new(token),
        }
    }

    pub fn set_token(&self, token: Option<String>) {
        *self.token.write().expect("token lock") = token;
    }

    pub fn has_token(&self) -> bool {
        self.token.read().expect("token lock").is_some()
    }

    pub fn token(&self) -> Option<String> {
        self.token.read().expect("token lock").clone()
    }

    async fn send(
        &self,
        request: reqwest::RequestBuilder,
        timeout: Duration,
    ) -> Result<Value, ApiError> {
        let token = self.token.read().expect("token lock").clone();
        self.send_as(request, timeout, token).await
    }

    /// Like `send`, with this token instead of the saved one (testing a key before saving).
    async fn send_as(
        &self,
        request: reqwest::RequestBuilder,
        timeout: Duration,
        token: Option<String>,
    ) -> Result<Value, ApiError> {
        let request = match token {
            Some(token) => request.bearer_auth(token),
            None => request,
        };
        let response = request.timeout(timeout).send().await?;
        let status = response.status();
        let text = response.text().await?;
        if !status.is_success() {
            return Err(ApiError {
                status: Some(status.as_u16()),
                detail: error_detail(&text),
                ..ApiError::new(error_code(status.as_u16(), &text))
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

    /// `POST /api/bug-reports`: 👎 "Hatalı" on an answer (the server fills in the rest).
    pub async fn report_bug(
        &self,
        base: &str,
        message_id: Option<i64>,
        note: &str,
        user_text: &str,
        reply_text: &str,
        error: Option<&str>,
    ) -> Result<Value, ApiError> {
        let body = json!({
            "message_id": message_id,
            "note": note,
            "source": "desktop",
            "user_text": user_text,
            "reply_text": reply_text,
            "error": error,
        });
        let request = self.http.post(format!("{base}/api/bug-reports")).json(&body);
        self.send(request, SHORT_TIMEOUT).await
    }

    /// `POST /api/screen-time`: whole days, replaced on the backend (idempotent).
    pub async fn screen_time(&self, base: &str, body: &Value) -> Result<Value, ApiError> {
        let request = self.http.post(format!("{base}/api/screen-time")).json(body);
        self.send(request, SHORT_TIMEOUT).await
    }

    /// `POST /api/auth/login`; `Ok(None)` = the server has no password (nothing to keep).
    pub async fn login(
        &self,
        base: &str,
        password: &str,
        device: &str,
    ) -> Result<Option<String>, ApiError> {
        let body = json!({ "password": password, "client": "desktop", "device": device });
        let request = self.http.post(format!("{base}/api/auth/login")).json(&body);
        let value = self.send(request, SHORT_TIMEOUT).await?;
        Ok(value
            .get("token")
            .and_then(Value::as_str)
            .map(str::to_owned))
    }

    /// `POST /api/auth/logout`: ends the session on the server too.
    pub async fn logout(&self, base: &str) -> Result<Value, ApiError> {
        let request = self.http.post(format!("{base}/api/auth/logout"));
        self.send(request, SHORT_TIMEOUT).await
    }

    /// `GET /api/team`: names and label colors; also the "is the server there?" check.
    pub async fn team(&self, base: &str) -> Result<Value, ApiError> {
        let request = self.http.get(format!("{base}/api/team"));
        self.send(request, SHORT_TIMEOUT).await
    }

    /// `GET /api/team` with a given token (None: without any): "Bağlantıyı test et".
    pub async fn team_as(&self, base: &str, token: Option<String>) -> Result<Value, ApiError> {
        let request = self.http.get(format!("{base}/api/team"));
        self.send_as(request, SHORT_TIMEOUT, token).await
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

/// Auth failures get their own codes (the panel says what to do); the rest is `http`.
fn error_code(status: u16, body: &str) -> &'static str {
    let code = serde_json::from_str::<Value>(body).ok().and_then(|v| {
        v.pointer("/detail/code")
            .and_then(Value::as_str)
            .map(str::to_owned)
    });
    match (status, code.as_deref()) {
        (401, Some("wrong_password")) => "wrong_password",
        (401, Some("device_key_invalid")) => "device_key_invalid",
        (401, _) => "login_required",
        (429, _) => "too_many_attempts",
        _ => "http",
    }
}

/// A device key from the web app (Durum → Cihaz anahtarları): `yvk_` + 43 url-safe chars.
pub fn is_device_key(key: &str) -> bool {
    key.strip_prefix("yvk_").is_some_and(|rest| {
        rest.len() >= 20
            && rest
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    })
}

/// Keeps the id from smuggling extra path segments into the URL.
fn uuid_like(id: &str) -> bool {
    !id.is_empty() && id.len() <= 64 && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-')
}

#[cfg(test)]
mod key_tests {
    use super::*;

    #[test]
    fn device_keys_are_recognised() {
        assert!(is_device_key(
            "yvk_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_xyz"
        ));
        assert!(!is_device_key("AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"));
        assert!(!is_device_key("yvk_short"));
        assert!(!is_device_key("yvk_has spaces and more characters here"));
    }

    #[test]
    fn a_revoked_key_has_its_own_code() {
        let body = r#"{"detail": {"code": "device_key_invalid"}}"#;
        assert_eq!(error_code(401, body), "device_key_invalid");
        assert_eq!(
            error_code(401, r#"{"detail": {"code": "login_required"}}"#),
            "login_required"
        );
    }
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
    fn auth_errors_have_their_own_codes() {
        assert_eq!(
            error_code(401, r#"{"detail": {"code": "login_required"}}"#),
            "login_required"
        );
        assert_eq!(
            error_code(401, r#"{"detail": {"code": "wrong_password"}}"#),
            "wrong_password"
        );
        assert_eq!(error_code(401, "<html>"), "login_required");
        assert_eq!(
            error_code(429, r#"{"detail": {"code": "too_many_attempts"}}"#),
            "too_many_attempts"
        );
        assert_eq!(error_code(500, ""), "http");
    }

    #[test]
    fn change_set_ids_are_checked() {
        assert!(uuid_like("3f2b8c1e-0d4a-4c7e-9a51-2b6f0e9d1c33"));
        assert!(!uuid_like("../../health"));
        assert!(!uuid_like(""));
    }
}
