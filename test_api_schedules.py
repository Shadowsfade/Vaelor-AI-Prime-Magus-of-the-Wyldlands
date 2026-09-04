from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api.server as server
from core.scheduler import ScheduleStore
from core.api_security import ApiAccessPolicy


class ScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ScheduleStore(Path(self.temp.name) / "schedules.json")
        self.patcher = patch.object(server, "schedule_store", self.store)
        self.patcher.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        self.client.close()
        self.patcher.stop()
        self.temp.cleanup()

    def test_create_list_pause_and_resume(self):
        created = self.client.post("/schedules", json={
            "name": "status check", "prompt": "inspect status", "interval_seconds": 300,
        })
        self.assertEqual(created.status_code, 200)
        schedule_id = created.json()["id"]
        listed = self.client.get("/schedules").json()["schedules"]
        self.assertEqual([item["id"] for item in listed], [schedule_id])
        paused = self.client.patch(f"/schedules/{schedule_id}", json={"enabled": False})
        self.assertEqual(paused.status_code, 200)
        self.assertFalse(paused.json()["enabled"])
        resumed = self.client.patch(f"/schedules/{schedule_id}", json={"enabled": True})
        self.assertTrue(resumed.json()["enabled"])

    def test_interval_below_five_minutes_is_rejected(self):
        response = self.client.post("/schedules", json={
            "name": "too fast", "prompt": "inspect", "interval_seconds": 60,
        })
        self.assertEqual(response.status_code, 422)

    def test_unknown_schedule_returns_not_found(self):
        response = self.client.patch("/schedules/missing", json={"enabled": False})
        self.assertEqual(response.status_code, 404)

    def test_cors_allows_loopback_but_not_arbitrary_websites(self):
        headers = {
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        }
        denied = self.client.options("/tasks", headers=headers)
        self.assertNotEqual(denied.headers.get("access-control-allow-origin"), "https://evil.example")
        headers["Origin"] = "http://localhost:8765"
        allowed = self.client.options("/tasks", headers=headers)
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:8765")

    def test_browser_token_exchange_rejects_unconfigured_or_wrong_token(self):
        response = self.client.post(
            "/auth/token", headers={"Authorization": "Bearer " + "x" * 40}
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("vaelor_api_token", response.cookies)

    def test_local_browser_auth_status_requires_no_token(self):
        response = self.client.get("/auth/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"authentication_required": False, "authenticated": True},
        )

    def test_valid_browser_exchange_sets_strict_httponly_cookie(self):
        token = "z" * 40
        token_path = Path(self.temp.name) / "api_access.json"
        token_path.write_text(json.dumps({"token": token}), encoding="utf-8")
        with patch.object(server, "api_access_policy", ApiAccessPolicy(token_path)):
            response = self.client.post(
                "/auth/token", headers={"Authorization": "Bearer " + token}
            )
        self.assertEqual(response.status_code, 200)
        cookie = response.headers.get("set-cookie", "").lower()
        self.assertIn("vaelor_api_token=", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)


if __name__ == "__main__":
    unittest.main()
