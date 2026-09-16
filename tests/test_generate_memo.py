import io
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
from openai import APIStatusError, OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_memo


class GenerateMemoTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "prompt").mkdir()
        for name in ("editorial-baseline.md", "cloud-runbook.md"):
            (self.root / "prompt" / name).write_text("Test instructions.")
        (self.root / "memos").mkdir()
        self.destination = self.root / "memos" / "memo-2026-09-15.md"
        self.destination.write_text("Previous valid edition\n")
        self.memo = (
            "Morning Market Memo | 15 Sep 2026 | HK/China Pre-Open\n"
            "(covers 14 Sep 16:00 HKT close → 15 Sep 06:45 HKT research cutoff)\n"
            + "\n".join(
                f"- Item {i}: Confirmed news. [[Source](https://example.com/{i})]"
                for i in range(8)
            )
        )
        self.stack.enter_context(patch.object(generate_memo, "ROOT", self.root))
        clock = self.stack.enter_context(patch.object(generate_memo, "datetime"))
        clock.now.return_value = datetime(2026, 9, 15, 6, 40, tzinfo=ZoneInfo("Asia/Hong_Kong"))
        self.stack.enter_context(patch.dict("os.environ", {"EDITION_MODE": "preopen"}))
        self.sleep = self.stack.enter_context(patch("time.sleep"))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.requests = []

    def transport(self, outcomes, error_code=None):
        def handle(request):
            self.requests.append(request)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome != 200:
                return httpx.Response(outcome, json={"error": {
                    "message": "Sensitive error detail must not be logged",
                    "code": error_code or ("server_is_overloaded" if outcome == 503 else "test_error"),
                }})
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 0,
                "model": "test", "status": "completed",
                "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": self.memo, "annotations": []}]}],
            })

        def client_factory(**kwargs):
            http_client = httpx.Client(transport=httpx.MockTransport(handle))
            client = OpenAI(api_key="test-only", http_client=http_client, **kwargs)
            self.stack.callback(client.close)
            return client

        self.stack.enter_context(patch.object(generate_memo, "OpenAI", side_effect=client_factory))

    def test_recovers_from_overload_after_default_sdk_retries_would_exhaust(self):
        self.transport([503, 503, 503, 200])
        try:
            generate_memo.main()
        except APIStatusError:
            self.fail("A temporary overload should recover on the fourth attempt")
        self.assertEqual(self.destination.read_text(), self.memo + "\n")
        self.assertEqual(len(self.requests), 4)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [15, 30, 60])
        self.assertNotIn("Sensitive error detail", self.output.getvalue())

    def test_exhaustion_stops_and_preserves_previous_memo(self):
        self.transport([503] * 10)
        with self.assertRaises(APIStatusError):
            generate_memo.main()
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(self.sleep.call_count, 3)
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")
        self.assertFalse(list((self.root / "memos").glob(".*.candidate")))

    def test_permanent_errors_fail_without_retry(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.requests.clear()
                self.sleep.reset_mock()
                self.transport([status])
                with self.assertRaises(APIStatusError):
                    generate_memo.main()
                self.assertEqual(len(self.requests), 1)
                self.sleep.assert_not_called()
                self.assertEqual(self.destination.read_text(), "Previous valid edition\n")

    def test_connection_timeout_recovers(self):
        self.transport([httpx.ReadTimeout("test timeout"), 200])
        generate_memo.main()
        self.assertEqual(self.destination.read_text(), self.memo + "\n")
        self.sleep.assert_called_once_with(15)

    def test_transient_http_errors_recover(self):
        for status in (408, 409, 429, 500, 502, 504):
            with self.subTest(status=status):
                self.requests.clear()
                self.sleep.reset_mock()
                self.transport([status, 200])
                generate_memo.main()
                self.assertEqual(len(self.requests), 2)
                self.sleep.assert_called_once_with(15)
                self.assertEqual(self.destination.read_text(), self.memo + "\n")

    def test_exhausted_quota_is_not_retried(self):
        self.transport([429], error_code="insufficient_quota")
        with self.assertRaises(APIStatusError):
            generate_memo.main()
        self.assertEqual(len(self.requests), 1)
        self.sleep.assert_not_called()
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")

    def test_validation_failure_is_not_retried_or_published(self):
        self.memo = "Invalid memo without sources"
        self.transport([200])
        with self.assertRaises(ValueError):
            generate_memo.main()
        self.assertEqual(len(self.requests), 1)
        self.sleep.assert_not_called()
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")

    def test_success_does_not_retry(self):
        self.transport([200])
        generate_memo.main()
        self.assertEqual(len(self.requests), 1)
        self.sleep.assert_not_called()
        self.assertEqual(self.destination.read_text(), self.memo + "\n")
        self.assertEqual(self.requests[0].extensions["timeout"]["read"], 300.0)


if __name__ == "__main__":
    unittest.main()
