import json
import re
import sys
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate_memo
from quality_audit import FACTS_AUDIT_SCHEMA, COVERAGE_AUDIT_SCHEMA


class ParallelAuditTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime.fromisoformat('2026-09-14T16:00:00+08:00')
        self.cutoff = datetime.fromisoformat('2026-09-15T06:40:00+08:00')
        self.markdown = '\n'.join(f'- Item {i}: Fact. [[Source](https://example.com/{i})]' for i in range(18))
        self.deadline = time.monotonic() + 30
        self.recorded = []

    def response(self, instruction, schema):
        if schema == COVERAGE_AUDIT_SCHEMA:
            body = {'coverage': [], 'editorial_issues': []}
            ids = []
        else:
            self.assertEqual(schema, FACTS_AUDIT_SCHEMA)
            batch = instruction.split('BATCH BULLETS START\n', 1)[1]
            ids = [int(value) for value in re.findall(r'^- Item (\d+):', batch, re.M)]
            self.assertGreater(len(ids), 0)
            self.assertLessEqual(len(ids), 3)
            # Deliberately return local numbers out of order; global mapping must be exact.
            body = {'items': [{'bullet': local + 1, 'fact_marker': global_id}
                              for local, global_id in reversed(list(enumerate(ids)))]}
        output = [{'type': 'web_search_call', 'status': 'completed',
                   'action': {'type': 'open_page', 'url': f'https://example.com/{i}'}} for i in ids]
        return SimpleNamespace(output_text=json.dumps(body), model_dump=lambda: {'output': output})

    def run_audit(self):
        return generate_memo.parallel_audit(object(), self.markdown, self.start, self.cutoff,
                                           deadline=self.deadline,
                                           record_response=lambda response, stage: self.recorded.append(stage))

    def test_four_worker_bound_shared_deadline_exact_global_mapping_and_local_provenance(self):
        lock = threading.Lock()
        first_wave = threading.Barrier(4)
        active = peak = calls = 0
        deadlines = []

        def request(client, instruction, *, audit, audit_schema, deadline):
            nonlocal active, peak, calls
            with lock:
                active += 1
                peak = max(peak, active)
                calls += 1
                number = calls
                deadlines.append(deadline)
            try:
                if number <= 4:
                    first_wave.wait(timeout=3)
                return self.response(instruction, audit_schema)
            finally:
                with lock:
                    active -= 1

        with patch.object(generate_memo, 'request_memo', side_effect=request):
            result, provenance = self.run_audit()
        self.assertEqual(peak, 4)
        self.assertEqual(calls, 7)  # Six three-bullet batches plus one coverage review.
        self.assertEqual(deadlines, [self.deadline] * 7)
        self.assertEqual([item['bullet'] for item in result['items']], list(range(1, 19)))
        self.assertEqual([item['fact_marker'] for item in result['items']], list(range(18)))
        self.assertEqual(provenance['items'][1]['opened'], {f'https://example.com/{i}' for i in range(3)})
        self.assertEqual(len(provenance['opened']), 18)
        self.assertEqual(len(self.recorded), 7)

    def test_failed_batch_never_returns_a_partial_audit(self):
        def request(client, instruction, *, audit, audit_schema, deadline):
            if 'BATCH BULLETS START\n- Item 3:' in instruction:
                raise ValueError('one facts batch failed')
            return self.response(instruction, audit_schema)
        with patch.object(generate_memo, 'request_memo', side_effect=request):
            with self.assertRaisesRegex(ValueError, 'one facts batch failed'):
                self.run_audit()

    def test_missing_or_duplicate_local_bullets_cannot_merge_as_complete(self):
        def request(client, instruction, *, audit, audit_schema, deadline):
            response = self.response(instruction, audit_schema)
            if audit_schema == FACTS_AUDIT_SCHEMA:
                result = json.loads(response.output_text)
                result['items'][0]['bullet'] = result['items'][1]['bullet']
                response.output_text = json.dumps(result)
            return response
        with patch.object(generate_memo, 'request_memo', side_effect=request):
            with self.assertRaisesRegex(ValueError, 'each local bullet exactly once'):
                self.run_audit()

    def test_expired_deadline_prevents_any_paid_parallel_work(self):
        self.deadline = time.monotonic() + 1
        with patch.object(generate_memo, 'request_memo') as request:
            with self.assertRaises(TimeoutError):
                self.run_audit()
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
