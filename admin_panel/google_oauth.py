from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.urls import reverse

GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

GOOGLE_OAUTH_SCOPES = [
    GOOGLE_DRIVE_SCOPE,
    GOOGLE_SHEETS_READONLY_SCOPE,
]
GOOGLE_OAUTH_DOWNLOAD_SCOPES = [GOOGLE_DRIVE_READONLY_SCOPE, GOOGLE_SHEETS_READONLY_SCOPE]
GOOGLE_OAUTH_UPLOAD_SCOPES = [GOOGLE_DRIVE_SCOPE]

GOOGLE_OAUTH_STATE_SESSION_KEY = "google_oauth_state"
GOOGLE_OAUTH_NEXT_SESSION_KEY = "google_oauth_next"
GOOGLE_OAUTH_CODE_VERIFIER_SESSION_KEY = "google_oauth_code_verifier"


class GoogleOAuthConfigError(RuntimeError):
    """Raised when Google OAuth cannot be started or completed."""


def _map_container_path_to_local_project(path: Path) -> Path:
    path_text = str(path).replace("\\", "/")
    base_text = str(settings.BASE_DIR).replace("\\", "/").rstrip("/")
    if path_text.startswith("/app/") and base_text != "/app":
        return Path(settings.BASE_DIR, path_text.removeprefix("/app/"))
    return path


def _configured_path(env_name: str, default: Path) -> Path:
    raw = (os.getenv(env_name) or "").strip()
    if not raw:
        return default

    path = Path(raw)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR, path)
    return _map_container_path_to_local_project(path)


def get_google_oauth_client_secret_path() -> Path:
    return _configured_path(
        "GOOGLE_OAUTH_CLIENT_SECRET_PATH",
        Path(settings.BASE_DIR, "creds", "google", "client_secret.json"),
    )


def get_google_oauth_token_path() -> Path:
    return _configured_path(
        "GOOGLE_OAUTH_TOKEN_PATH",
        Path(settings.BASE_DIR, "creds", "google", "token.json"),
    )


def get_google_oauth_redirect_uri(request) -> str:
    configured = (os.getenv("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    if configured:
        return configured
    return request.build_absolute_uri(reverse("journal_links:google_oauth_callback"))


def _allow_local_insecure_transport(redirect_uri: str) -> None:
    parsed = urlparse(redirect_uri)
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}:
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _build_flow(request, *, state: str | None = None, code_verifier: str | None = None):
    client_secret_path = get_google_oauth_client_secret_path()
    if not client_secret_path.exists():
        raise GoogleOAuthConfigError(f"Google OAuth client secret not found: {client_secret_path}")

    redirect_uri = get_google_oauth_redirect_uri(request)
    _allow_local_insecure_transport(redirect_uri)

    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_secrets_file(
        str(client_secret_path),
        scopes=GOOGLE_OAUTH_SCOPES,
        redirect_uri=redirect_uri,
        state=state,
        code_verifier=code_verifier,
    )


def build_google_authorization_url(request) -> tuple[str, str, str]:
    flow = _build_flow(request)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    if not flow.code_verifier:
        raise GoogleOAuthConfigError("Google OAuth did not create a PKCE code verifier")
    return authorization_url, state, flow.code_verifier


def complete_google_oauth(request, *, state: str, code_verifier: str | None) -> Path:
    if not code_verifier:
        raise GoogleOAuthConfigError("OAuth session expired: missing PKCE code verifier. Start Google connection again.")

    flow = _build_flow(request, state=state, code_verifier=code_verifier)
    authorization_response = request.build_absolute_uri()
    _allow_local_insecure_transport(authorization_response)
    flow.fetch_token(authorization_response=authorization_response)

    token_path = get_google_oauth_token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(flow.credentials.to_json(), encoding="utf-8")
    return token_path


def get_google_oauth_status() -> dict:
    client_secret_path = get_google_oauth_client_secret_path()
    token_path = get_google_oauth_token_path()
    token_exists = token_path.exists()
    token_has_refresh_token = False
    token_expiry = ""
    token_error = ""

    if token_exists:
        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
            token_has_refresh_token = bool(token_data.get("refresh_token"))
            token_expiry = str(token_data.get("expiry") or "")
        except (OSError, json.JSONDecodeError) as exc:
            token_error = str(exc)

    return {
        "client_secret_path": str(client_secret_path),
        "client_secret_exists": client_secret_path.exists(),
        "token_path": str(token_path),
        "token_exists": token_exists,
        "token_has_refresh_token": token_has_refresh_token,
        "token_expiry": token_expiry,
        "token_error": token_error,
        "is_ready": client_secret_path.exists() and token_exists and token_has_refresh_token and not token_error,
    }
