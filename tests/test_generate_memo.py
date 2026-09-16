import io
import json
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
            "(covers 14 Sep 16:00 HKT close → 15 Sep 06:40 HKT research cutoff)\n"
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

    def audit(self):
        from quality_audit import COVERAGE_AREAS
        return {
            "items": [{"bullet": i + 1, "supported": True, "freshness": "new",
                       "event_time_hkt": "2026-09-15T05:00:00+08:00",
                       "source_published_at": "2026-09-15T05:30:00+08:00",
                       "evidence": "Official source confirms the stated event and its exact figures.",
                       "checked_facts": ["issuer, event, amount, time"],
                       "source_urls": [f"https://example.com/{i}"],
                       "source_checks": [{"url": f"https://example.com/{i}", "published_at": "2026-09-15T05:30:00+08:00",
                                          "checked_facts": ["issuer announcement confirms amount and event"]}], "issues": []} for i in range(8)],
            "coverage": [{"area": area, "queries": ["independent query"],
                          "finding": "Verified the latest relevant notices and no additional material stories.",
                          "source_urls": ["https://example.com/0"], "missing_material_stories": []}
                         for area in COVERAGE_AREAS],
            "editorial_issues": [],
        }

    def transport(self, outcomes, error_code=None):
        def handle(request):
            self.requests.append(request)
            is_audit = "text" in json.loads(request.content)
            outcome = 200 if is_audit else outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome != 200:
                return httpx.Response(outcome, json={"error": {
                    "message": "Sensitive error detail must not be logged",
                    "code": error_code or ("server_is_overloaded" if outcome == 503 else "test_error"),
                }})
            text = json.dumps(self.audit()) if is_audit else self.memo
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 0,
                "model": "test", "status": "completed",
                "output": [{"id": f"open_{i}", "type": "web_search_call", "status": "completed",
                            "action": {"type": "open_page", "url": f"https://example.com/{i}"}} for i in range(8)] + [{"id": "search_test", "type": "web_search_call", "status": "completed",
                            "action": {"type": "search", "query": "independent query", "sources": [
                            {"type": "url", "url": f"https://example.com/{i}"} for i in range(8)]}},
                           {"id": "msg_test", "type": "message", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": text, "annotations": []}]}],
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
        self.assertEqual(len(self.requests), 5)
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
                self.assertEqual(len(self.requests), 3)
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
        self.transport([200, 200])
        with self.assertRaises(ValueError):
            generate_memo.main()
        self.assertEqual(len(self.requests), 2)
        self.sleep.assert_not_called()
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")

    def test_success_does_not_retry(self):
        self.transport([200])
        generate_memo.main()
        self.assertEqual(len(self.requests), 2)
        self.sleep.assert_not_called()
        self.assertEqual(self.destination.read_text(), self.memo + "\n")
        self.assertEqual(self.requests[0].extensions["timeout"]["read"], 300.0)

    def test_failed_independent_audit_never_promotes(self):
        audit = self.audit()
        audit["items"][0]["supported"] = False
        with patch.object(self, "audit", return_value=audit):
            self.transport([200, 200])
            with self.assertRaisesRegex(ValueError, "unsupported"):
                generate_memo.main()
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")
        self.assertFalse(json.loads((self.root / "artifacts/memo-audit.json").read_text())["passed"])

    def test_validation_only_does_not_publish_and_saves_usage_receipt(self):
        self.transport([200])
        with patch.dict("os.environ", {"MEMO_VALIDATE_ONLY": "true"}):
            generate_memo.main()
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")
        self.assertFalse(self.destination.with_suffix(".status.json").exists())
        artifact = json.loads((self.root / "artifacts/memo-audit.json").read_text())
        self.assertTrue(artifact["passed"])
        self.assertEqual(artifact["research_cutoff"], "2026-09-15T06:40:00+08:00")
        self.assertEqual(len(artifact["checks"]), 1)

    def test_success_writes_hash_bound_public_safe_receipt(self):
        import hashlib
        self.transport([200])
        generate_memo.main()
        receipt = json.loads(self.destination.with_suffix(".status.json").read_text())
        self.assertTrue(receipt["qualityPassed"])
        self.assertEqual(receipt["memoSha256"], hashlib.sha256(self.destination.read_bytes()).hexdigest())
        self.assertNotIn("checks", receipt)

    def test_deadline_exhaustion_prevents_paid_requests(self):
        self.transport([200])
        with patch.dict("os.environ", {"MEMO_GENERATION_BUDGET_SECONDS": "1"}):
            with self.assertRaises(TimeoutError):
                generate_memo.main()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.destination.read_text(), "Previous valid edition\n")

    def test_provider_error_body_is_not_saved_in_artifact(self):
        self.transport([401])
        with self.assertRaises(APIStatusError):
            generate_memo.main()
        self.assertNotIn("Sensitive error detail", (self.root / "artifacts/memo-audit.json").read_text())

    def test_model_clock_cannot_override_machine_cutoff(self):
        self.memo = self.memo.replace("06:40 HKT", "09:29 HKT")
        self.transport([200])
        generate_memo.main()
        self.assertIn("06:40 HKT research cutoff", self.destination.read_text())
        self.assertNotIn("09:29 HKT", self.destination.read_text())

    def test_stage_deadline_reserves_required_audit_time(self):
        with patch.object(generate_memo.time, "monotonic", return_value=100):
            self.assertEqual(generate_memo.stage_deadline(1420, 600, 360), 700)
            self.assertEqual(generate_memo.stage_deadline(800, 600, 360), 440)
            self.assertEqual(generate_memo.stage_deadline(800, 600), 700)

    def test_artifact_retains_actual_tool_provenance(self):
        self.transport([200])
        generate_memo.main()
        artifact = json.loads((self.root / "artifacts/memo-audit.json").read_text())
        self.assertEqual([entry["stage"] for entry in artifact["retrieval"]], ["draft", "audit"])
        self.assertEqual(artifact["retrieval"][0]["queries"], ["independent query"])
        self.assertEqual(artifact["retrieval"][0]["unmatched_citations"], [])
        self.assertEqual(len(artifact["retrieval"][0]["urls"]), 8)
        self.assertEqual(len(artifact["retrieval"][1]["opened_urls"]), 8)

    def test_signed_url_values_are_redacted_in_diagnostics(self):
        url = generate_memo.diagnostic_url("https://example.com/news?id=3&token=secret&X-Amz-Signature=hidden")
        self.assertNotIn("secret", url)
        self.assertNotIn("hidden", url)
        self.assertIn("id=3", url)


if __name__ == "__main__":
    unittest.main()
