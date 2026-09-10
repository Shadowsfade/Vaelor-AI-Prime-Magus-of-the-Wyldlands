"""Small synchronous ASGI client for the Python 3.14 test environment.

The bundled Starlette TestClient's blocking portal does not schedule calls
correctly with this interpreter/runtime combination.  Keep API tests
deterministic by using httpx's direct ASGI transport instead; production code
and filesystem policy are unaffected.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import starlette.testclient


class SynchronousASGIClient:
    __test__ = False

    def __init__(self, app, base_url: str = "http://testserver", **_: Any):
        self.app = app
        self.base_url = base_url
        self.cookies = httpx.Cookies()

    async def _request_async(self, method: str, url: str, **kwargs: Any):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, client=("testclient", 50000)),
            base_url=self.base_url,
            cookies=self.cookies,
        ) as client:
            response = await client.request(method, url, **kwargs)
            self.cookies.update(client.cookies)
            return response

    def request(self, method: str, url: str, **kwargs: Any):
        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs: Any):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any):
        return self.request("PATCH", url, **kwargs)

    def options(self, url: str, **kwargs: Any):
        return self.request("OPTIONS", url, **kwargs)

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


starlette.testclient.TestClient = SynchronousASGIClient
