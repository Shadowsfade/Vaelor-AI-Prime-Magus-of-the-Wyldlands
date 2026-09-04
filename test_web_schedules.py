from pathlib import Path
import unittest


HTML = (Path(__file__).resolve().parent / "web" / "index.html").read_text(
    encoding="utf-8-sig"
)


class WebScheduleRegressionTests(unittest.TestCase):
    def test_tome_lists_scheduled_rituals(self):
        self.assertIn("Scheduled Rituals", HTML)
        self.assertIn('id="scheduleList"', HTML)
        self.assertIn("fetch('/schedules?limit=20')", HTML)
        self.assertIn("schedule.next_run_at", HTML)
        self.assertIn("schedule.run_count", HTML)
        self.assertIn("schedule.last_error", HTML)

    def test_schedule_pause_resume_uses_exact_id_and_boolean(self):
        self.assertIn("data-enabled=", HTML)
        self.assertIn("`/schedules/${encodeURIComponent(id)}`", HTML)
        self.assertIn("method:'PATCH'", HTML)
        self.assertIn("JSON.stringify({enabled})", HTML)

    def test_last_scheduled_task_opens_existing_live_console(self):
        self.assertIn("schedule.last_task_id", HTML)
        self.assertIn("watchTask(b.dataset.taskId)", HTML)

    def test_schedule_text_is_escaped_before_html_rendering(self):
        self.assertIn("escapeHtml(schedule.name", HTML)
        self.assertIn("escapeHtml(error)", HTML)

    def test_cover_uses_canonical_prime_magus_title(self):
        self.assertIn("Prime Magus of the Wyldlands", HTML)
        self.assertNotIn("Arcane Archivist of the Wyldlands", HTML)


if __name__ == "__main__":
    unittest.main()
