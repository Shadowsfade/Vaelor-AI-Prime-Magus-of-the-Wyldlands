"""Lifespan-correct synchronous ASGI client for Python 3.14 tests.

Starlette's bundled blocking portal and HTTPX's direct ASGI transport are
incompatible with this interpreter combination. This test-only client owns
one event loop and one ASGI lifespan task for its entire lifetime. Production
request handling is untouched and application exceptions are propagated.
"""
from __future__ import annotations

import asyncio
from typing import Any
import warnings

import httpx


async def _python314_threadpool(func, *args, **kwargs):
    """Run test handlers inline; Python 3.14's executor reuse stalls here."""
    return func(*args, **kwargs)


# Test-only compatibility for the pinned Python 3.14 environment. This keeps
# production request behavior untouched and does not replace TestClient users.
import fastapi.routing
import starlette.background
import starlette.concurrency
import starlette.routing
fastapi.routing.run_in_threadpool = _python314_threadpool
starlette.background.run_in_threadpool = _python314_threadpool
starlette.concurrency.run_in_threadpool = _python314_threadpool
starlette.routing.run_in_threadpool = _python314_threadpool

# These are pinned third-party Python 3.14 compatibility warnings. Vaelor's
# deprecated lifespan handlers were migrated to api.server.lifespan; keep
# third-party warnings narrow and do not hide warnings from Vaelor modules.
warnings.filterwarnings(
    "ignore", message=r"The anyio\.abc\.BlockingPortal alias is deprecated.*",
    category=DeprecationWarning, module=r"starlette\.testclient",
)
warnings.filterwarnings(
    "ignore", message=r"'asyncio\.iscoroutinefunction' is deprecated.*",
    category=DeprecationWarning, module=r"fastapi\.routing",
)


class SynchronousASGIClient:
    __test__ = False

    def __init__(self, app, base_url: str = "http://testserver", **_: Any):
        self.app = app
        self.base_url = base_url
        self.cookies = httpx.Cookies()
        self._closed = False
        self._runner = asyncio.Runner()
        try:
            self._runner.run(self._startup())
        except BaseException:
            self._runner.close()
            raise

    async def _startup(self) -> None:
        self._lifespan_send: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._lifespan_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def receive() -> dict[str, Any]:
            return await self._lifespan_send.get()

        async def send(message: dict[str, Any]) -> None:
            await self._lifespan_events.put(message)

        scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}}
        self._lifespan_task = asyncio.create_task(self.app(scope, receive, send))
        await self._lifespan_send.put({"type": "lifespan.startup"})
        message = await self._lifespan_events.get()
        if message["type"] == "lifespan.startup.failed":
            try:
                await self._lifespan_task
            except BaseException as exc:
                raise exc
            raise RuntimeError(message.get("message", "ASGI lifespan startup failed"))
        if message["type"] != "lifespan.startup.complete":
            raise RuntimeError(f"unexpected ASGI lifespan message: {message['type']}")

    async def _shutdown(self) -> None:
        if getattr(self, "_lifespan_task", None) is not None:
            await self._lifespan_send.put({"type": "lifespan.shutdown"})
            message = await self._lifespan_events.get()
            if message["type"] == "lifespan.shutdown.failed":
                raise RuntimeError(message.get("message", "ASGI lifespan shutdown failed"))
            await self._lifespan_task

    async def _request_async(self, method: str, url: str, **kwargs: Any):
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.cookies and not any(str(key).lower() == "cookie" for key in headers):
            headers["cookie"] = "; ".join(f"{key}={value}" for key, value in self.cookies.items())
        request = httpx.Request(
            method, httpx.URL(self.base_url).join(url), headers=headers, **kwargs
        )
        body = request.read()
        messages: list[dict[str, Any]] = []
        received = False

        async def receive() -> dict[str, Any]:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        parsed = request.url
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": method.upper(), "scheme": parsed.scheme,
            "path": parsed.path, "raw_path": parsed.raw_path,
            "query_string": parsed.query,
            "headers": [(key.lower(), value) for key, value in request.headers.raw],
            "client": ("testclient", 50000), "server": (parsed.host, parsed.port or 80),
        }
        await self.app(scope, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        response = httpx.Response(start["status"], headers=start.get("headers", []), content=content, request=request)
        self.cookies.update(response.cookies)
        return response

    def _request_sync(self, method: str, url: str, **kwargs: Any):
        if self._closed:
            raise RuntimeError("ASGI test client is closed")
        return self._runner.run(self._request_async(method, url, **kwargs))

    def request(self, method: str, url: str, **kwargs: Any):
        return self._request_sync(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any):
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any):
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any):
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any):
        return self.request("OPTIONS", url, **kwargs)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._runner.run(self._shutdown())
        finally:
            self._runner.close()
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
