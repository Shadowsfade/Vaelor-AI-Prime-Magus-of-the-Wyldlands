import threading
import unittest
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from conftest import SynchronousASGIClient as TestClient

import api.server as server


class _LifecycleProbe:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class ApiLifespanTests(unittest.TestCase):
    def test_scheduler_starts_and_stops_exactly_once_per_client(self):
        probe = _LifecycleProbe()
        original = server.scheduler_service
        server.scheduler_service = probe
        try:
            with TestClient(server.app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(probe.started, 1)
                self.assertEqual(probe.stopped, 0)
            self.assertEqual(probe.started, 1)
            self.assertEqual(probe.stopped, 1)
        finally:
            server.scheduler_service = original

    def test_client_identity_and_cookies_persist(self):
        app = FastAPI()

        @app.get("/set")
        async def set_cookie(response: Response):
            response.set_cookie("session", "kept", httponly=True)
            return {"ok": True}

        @app.get("/check")
        async def check(request: Request):
            return {"cookie": request.cookies.get("session"), "client": request.client.host}

        with TestClient(app) as client:
            self.assertEqual(client.get("/set").status_code, 200)
            checked = client.get("/check").json()
        self.assertEqual(checked, {"cookie": "kept", "client": "testclient"})

    def test_application_exceptions_propagate(self):
        app = FastAPI()

        @app.get("/boom")
        async def boom():
            raise RuntimeError("visible application failure")

        with self.assertRaisesRegex(RuntimeError, "visible application failure"):
            with TestClient(app) as client:
                client.get("/boom")

    def test_repeated_clients_do_not_leave_test_threads(self):
        before = {thread.ident for thread in threading.enumerate() if thread.name == "vaelor-test-asgi"}
        probe = _LifecycleProbe()
        original = server.scheduler_service
        server.scheduler_service = probe
        try:
            for _ in range(3):
                with TestClient(server.app) as client:
                    self.assertEqual(client.get("/health").status_code, 200)
        finally:
            server.scheduler_service = original
        self.assertEqual((probe.started, probe.stopped), (3, 3))
        after = {thread.ident for thread in threading.enumerate() if thread.name == "vaelor-test-asgi"}
        self.assertEqual(after, before)

    def test_startup_failure_does_not_leave_client_thread(self):
        @asynccontextmanager
        async def failing_lifespan(_app):
            raise RuntimeError("startup failed")
            yield

        app = FastAPI(lifespan=failing_lifespan)
        with self.assertRaisesRegex(RuntimeError, "startup failed"):
            TestClient(app)
        self.assertFalse(any(thread.name == "vaelor-test-asgi" for thread in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
