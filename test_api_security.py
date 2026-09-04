import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from core.api_security import ApiAccessMiddleware, ApiAccessPolicy, generate_api_access_token


async def ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def request(middleware, client, host, headers=None):
    sent = []
    raw_headers = [(b"host", host.encode("ascii"))]
    raw_headers.extend(
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in (headers or {}).items()
    )
    scope = {"type": "http", "client": (client, 1234), "headers": raw_headers}
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        sent.append(message)
    asyncio.run(middleware(scope, receive, send))
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, json.loads(body) if body and body != b"ok" else body


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "api_access.json"
        self.policy = ApiAccessPolicy(self.path)
        self.middleware = ApiAccessMiddleware(ok_app, self.policy)

    def tearDown(self):
        self.temp.cleanup()

    def test_loopback_with_local_host_is_allowed_without_token(self):
        self.assertEqual(request(self.middleware, "127.0.0.1", "localhost:8765")[0], 200)
        self.assertEqual(request(self.middleware, "::1", "[::1]:8765")[0], 200)

    def test_dns_rebinding_host_is_rejected_even_from_loopback(self):
        status, body = request(self.middleware, "127.0.0.1", "evil.example")
        self.assertEqual(status, 403)
        self.assertIn("Host header", body["detail"])

    def test_remote_access_fails_closed_without_configured_token(self):
        status, body = request(self.middleware, "100.64.0.2", "vaelor.local")
        self.assertEqual(status, 403)
        self.assertIn("disabled", body["detail"])

    def test_remote_bearer_and_alternate_tokens_are_accepted(self):
        token = "a" * 40
        self.path.write_text(json.dumps({"token": token}), encoding="utf-8")
        bearer = request(
            self.middleware, "100.64.0.2", "vaelor.local",
            {"Authorization": f"Bearer {token}"},
        )
        alternate = request(
            self.middleware, "192.168.1.20", "vaelor.local",
            {"X-Vaelor-Token": token},
        )
        self.assertEqual(bearer[0], 200)
        self.assertEqual(alternate[0], 200)

    def test_short_or_wrong_token_never_enables_remote_access(self):
        self.path.write_text(json.dumps({"token": "short"}), encoding="utf-8")
        self.assertEqual(request(self.middleware, "10.0.0.2", "host", {"X-Vaelor-Token": "short"})[0], 403)
        token = "b" * 40
        self.path.write_text(json.dumps({"token": token}), encoding="utf-8")
        self.assertEqual(request(self.middleware, "10.0.0.2", "host", {"Authorization": "Bearer wrong"})[0], 403)

    def test_token_generation_is_strong_atomic_and_no_overwrite_by_default(self):
        token = generate_api_access_token(self.path)
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["token"], token)
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())
        with self.assertRaises(FileExistsError):
            generate_api_access_token(self.path)

    def test_status_never_reveals_token(self):
        token = generate_api_access_token(self.path)
        status = self.policy.status()
        self.assertTrue(status["remote_auth_enabled"])
        self.assertEqual(status["source"], "local_config")
        self.assertNotIn(token, json.dumps(status))


if __name__ == "__main__":
    unittest.main()
