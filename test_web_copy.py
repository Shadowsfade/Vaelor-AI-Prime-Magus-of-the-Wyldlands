from pathlib import Path
import unittest


HTML = (Path(__file__).resolve().parent / "web" / "index.html").read_text(
    encoding="utf-8-sig"
)


class WebCopyRegressionTests(unittest.TestCase):
    def test_message_copy_reads_live_message_state(self):
        self.assertIn("div._vaelorCopyText = String(text", HTML)
        self.assertIn("copyTextToClipboard(div._vaelorCopyText || '')", HTML)

    def test_stream_updates_live_copy_state(self):
        self.assertIn("function updateMessageContent(message, text, renderFinal)", HTML)
        self.assertIn("message.div._vaelorCopyText=current", HTML)
        self.assertIn("updateMessageContent(thinking,full,false)", HTML)

    def test_completed_stream_renders_markdown_and_code_copy_buttons(self):
        self.assertIn("updateMessageContent(thinking,full,true);", HTML)
        self.assertIn("wireCopyButtons(message.span);", HTML)


if __name__ == "__main__":
    unittest.main()
