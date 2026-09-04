"""ASGI boundary for loopback Host validation and authenticated remote API access."""
from __future__ import annotations

import hmac
from http.cookies import SimpleCookie
import ipaddress
import json
import os
from pathlib import Path
import secrets
from typing import Optional


LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def _is_loopback(value: str) -> bool:
    if value == "testclient":  # Starlette's in-process test transport, never a TCP peer.
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value.casefold() == "localhost"


def _hostname(host_header: str) -> str:
    value = str(host_header or "").strip().casefold()
    if value.startswith("["):
        end = value.find("]")
        return value[:end + 1] if end >= 0 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class ApiAccessPolicy:
    def __init__(self, config_path: Optional[Path] = None):
        root = Path(__file__).resolve().parent.parent
        self.config_path = Path(config_path or root / "config" / "api_access.json")

    def token(self) -> Optional[str]:
        env_token = os.environ.get("VAELOR_API_TOKEN", "").strip()
        if len(env_token) >= 32:
            return env_token
        if not self.config_path.is_file():
            return None
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            token = str(value.get("token", "")).strip() if isinstance(value, dict) else ""
            return token if len(token) >= 32 else None
        except Exception:
            return None

    def status(self) -> dict:
        env_valid = len(os.environ.get("VAELOR_API_TOKEN", "").strip()) >= 32
        return {
            "remote_auth_enabled": self.token() is not None,
            "source": "environment" if env_valid else (
                "local_config" if self.token() is not None else "none"
            ),
            "loopback_without_token": True,
            "remote_requires_token": True,
        }

    def authorize(self, client_host: str, host_header: str,
                  authorization: str = "", alternate_token: str = "",
                  cookie_token: str = "") -> tuple[bool, str]:
        if _is_loopback(client_host):
            if client_host == "testclient" or _hostname(host_header) in LOCAL_HOSTS:
                return True, "local"
            return False, "unrecognized local Host header"
        expected = self.token()
        if expected is None:
            return False, "remote API access is disabled"
        supplied = str(alternate_token or cookie_token or "").strip()
        auth = str(authorization or "").strip()
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if supplied and hmac.compare_digest(supplied, expected):
            return True, "authenticated_remote"
        return False, "valid API token required"


class ApiAccessMiddleware:
    def __init__(self, app, policy: Optional[ApiAccessPolicy] = None):
        self.app = app
        self.policy = policy or ApiAccessPolicy()

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        client = scope.get("client") or ("", 0)
        client_host = str(client[0])
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        if not _is_loopback(client_host) and method == "GET" and path in {"/", "/auth/status", "/favicon.ico"}:
            await self.app(scope, receive, send)
            return
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("cookie", ""))
            cookie_token = cookies.get("vaelor_api_token").value if cookies.get("vaelor_api_token") else ""
        except Exception:
            cookie_token = ""
        allowed, reason = self.policy.authorize(
            client_host, headers.get("host", ""), headers.get("authorization", ""),
            headers.get("x-vaelor-token", ""), cookie_token,
        )
        if allowed:
            await self.app(scope, receive, send)
            return
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 4403, "reason": reason})
            return
        body = json.dumps({"detail": reason}).encode("utf-8")
        await send({
            "type": "http.response.start", "status": 403,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii"))],
        })
        await send({"type": "http.response.body", "body": body})


def generate_api_access_token(config_path: Optional[Path] = None, force: bool = False) -> str:
    """Create one ignored local API token atomically; never overwrite it implicitly."""
    policy = ApiAccessPolicy(config_path)
    path = policy.config_path
    if path.exists() and not force:
        raise FileExistsError(f"API access config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"token": token}, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)
    return token
