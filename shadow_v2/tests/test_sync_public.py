import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from shadow_v2.sync_public import sync_public, PUBLIC_SITE
from shadow_v2.store import Store


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def write_receipt(root, content):
    (root/'docs').mkdir(exist_ok=True)
    (root/'docs/status.json').write_text(json.dumps({
        'editionDate':'2026-10-01', 'memoSha256':hashlib.sha256(content).hexdigest()}))


class SyncTests(unittest.TestCase):
    def test_delayed_receipt_then_same_day_revision_updates_private_edition(self):
        with tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
            root = Path(temp); (root/'memos').mkdir()
            memo = root/'memos/memo-2026-10-01.md'
            content = b'Title\n\n- Published first.\n'
            memo.write_bytes(content)
            write_receipt(root, content)
            clock = Clock(); attempts = []
            def fetch(url, timeout):
                attempts.append(url)
                if url == PUBLIC_SITE+'status.json':
                    digest = '0'*64 if len(attempts) == 1 else hashlib.sha256(content).hexdigest()
                    return json.dumps({'editionDate':'2026-10-01','memoSha256':digest}).encode()
                return content
            with patch('shadow_v2.sync_public.REPOSITORY', root):
                first = sync_public(store, fetch=fetch, clock=clock, sleep=clock.sleep)
                self.assertEqual(first, store.latest_edition())
                self.assertGreater(clock.now, 0)
                content = b'Title\n\n- Revised published story.\n';memo.write_bytes(content)
                write_receipt(root, content)
                revised = sync_public(store, fetch=fetch, clock=clock, sleep=clock.sleep)
            self.assertNotEqual(first['id'], revised['id'])
            self.assertEqual(store.latest_edition(), revised)
            self.assertEqual(revised['source_version'], 'sha256:'+hashlib.sha256(content).hexdigest())
            self.assertNotIn('observed_at', revised)

    def test_unpublished_head_or_mismatched_public_markdown_preserves_previous(self):
        for mismatch_checkout in (True, False):
            with self.subTest(checkout=mismatch_checkout), tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
                root=Path(temp);(root/'memos').mkdir()
                content=b'Title\n\n- Actual published.\n'
                memo=root/'memos/memo-2026-10-01.md';memo.write_bytes(content)
                write_receipt(root, content)
                clock=Clock()
                receipt=json.dumps({'editionDate':'2026-10-01','memoSha256':hashlib.sha256(content).hexdigest()}).encode()
                def fetch(url, timeout): return receipt if url.endswith('status.json') else content
                with patch('shadow_v2.sync_public.REPOSITORY',root):
                    prior=sync_public(store,fetch=fetch,clock=clock,sleep=clock.sleep)
                    if mismatch_checkout: memo.write_bytes(b'Title\n\n- Unpublished HEAD.\n')
                    else: content=b'Title\n\n- Public file disagrees with receipt.\n'
                    with self.assertRaises(RuntimeError):
                        sync_public(store,fetch=fetch,clock=clock,sleep=clock.sleep)
                self.assertEqual(store.latest_edition(),prior)
                self.assertLessEqual(clock.now,55)


if __name__ == '__main__': unittest.main()
