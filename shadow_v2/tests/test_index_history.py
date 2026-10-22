from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from shadow_v2.index_history import index_archive, embedding_text
from shadow_v2.policy import Budget
from shadow_v2.store import Store
from shadow_v2.models import parse_edition
import hashlib

def register_files(store, root):
    for memo in sorted((root/"memos").glob("*.md")):
        text=memo.read_text()
        store.register_edition(parse_edition(text,memo.stem[5:],"sha256:"+hashlib.sha256(text.encode()).hexdigest()))



class Adapter:
    model='fixture-model'
    version='fixture-1'
    last_usage={'total_tokens':10}
    def __init__(self):self.calls=0
    def embed(self,text):self.calls+=1;return [1.,0.]


class IndexTests(unittest.TestCase):
    def test_bounded_public_index_uses_stable_revisions(self):
        with tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
            root=Path(temp);(root/'memos').mkdir()
            (root/'memos/memo-2026-10-01.md').write_text('Title\n\n- One. [[S](https://example.com/one)]\n- Two. [[S](https://example.com/two)]\n')
            register_files(store, root)
            adapter=Adapter()
            with patch('shadow_v2.index_history.REPOSITORY',root):
                self.assertEqual(index_archive(store,adapter,Budget(1,30),.02,1),1)
                first=store.latest_edition()
                self.assertEqual(index_archive(store,adapter,Budget(1,30),.02,1),1)
            self.assertEqual(first,store.latest_edition())
            self.assertEqual(len(store.search_history([1.,0.],adapter.model,adapter.version)),2)
            with patch('shadow_v2.index_history.REPOSITORY',root):
                self.assertEqual(index_archive(store,adapter,Budget(0,30),.02,200),0)
            self.assertEqual(adapter.calls,2)
            self.assertNotIn('https://',embedding_text(first['items'][0]))

    def test_budget_denial_prevents_paid_call(self):
        with tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
            root=Path(temp);(root/'memos').mkdir();(root/'memos/memo-2026-10-01.md').write_text('T\n\n- A story. [[S](https://example.com/a)]')
            register_files(store, root)
            adapter=Adapter()
            with patch('shadow_v2.index_history.REPOSITORY',root),self.assertRaises(Exception):
                index_archive(store,adapter,Budget(0,30),1,1)
            self.assertEqual(adapter.calls,0)

    def test_new_edition_indexes_only_new_items_and_feedback_is_retrieved(self):
        with tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
            root=Path(temp);(root/'memos').mkdir()
            first=root/'memos/memo-2026-09-30.md'
            first.write_text('T\n\n- Prior story. [[S](https://example.com/a)]')
            register_files(store,root)
            adapter=Adapter()
            with patch('shadow_v2.index_history.REPOSITORY',root):
                self.assertEqual(index_archive(store,adapter,Budget(1,30),.02),1)
                second=root/'memos/memo-2026-10-01.md'
                second.write_text('T\n\n- New story. [[S](https://example.com/b)]')
                register_files(store,root)
                edition=store.latest_edition();item=edition['items'][0]
                store.add_feedback('reviewer',item['id'],'used','8d7ab0f7-3c23-4d61-a00d-0abbc23f4c2a',edition['id'])
                self.assertEqual(index_archive(store,adapter,Budget(1,30),.02),1)
                self.assertEqual(index_archive(store,adapter,Budget(0,30),.02),0)
            self.assertEqual(adapter.calls,2)
            found=store.search_history([1.,0.],adapter.model,adapter.version)
            self.assertTrue(any(row['id']==item['id'] and row['label']=='used' for row in found))
            self.assertEqual(store.get_item_feedback([item['id']])[item['id']],'used')

    def test_failed_index_retry_skips_previously_committed_vectors(self):
        with tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
            root=Path(temp);(root/'memos').mkdir()
            (root/'memos/memo-2026-10-01.md').write_text('T\n\n- First story.\n- Second story.')
            register_files(store,root)
            adapter=Adapter()
            original=adapter.embed
            def fail_second(text):
                if adapter.calls == 1:
                    raise RuntimeError('provider failure')
                return original(text)
            adapter.embed=fail_second
            with patch('shadow_v2.index_history.REPOSITORY',root):
                with self.assertRaises(RuntimeError):
                    index_archive(store,adapter,Budget(1,30),.02)
                self.assertEqual(adapter.calls,1)
                adapter.embed=original
                self.assertEqual(index_archive(store,adapter,Budget(1,30),.02),1)
            self.assertEqual(adapter.calls,2)

    def test_unregistered_checkout_never_indexes_or_becomes_latest(self):
        with tempfile.TemporaryDirectory() as temp, Store(':memory:') as store:
            root=Path(temp);(root/'memos').mkdir()
            (root/'memos/memo-2026-10-01.md').write_text('T\n\n- Unpublished story.')
            adapter=Adapter()
            with patch('shadow_v2.index_history.REPOSITORY',root):
                self.assertEqual(index_archive(store,adapter,Budget(1,30),.02),0)
            self.assertIsNone(store.latest_edition())
            self.assertEqual(adapter.calls,0)

    def test_nonfinite_rate_rejected(self):
        with Store(':memory:') as store:
            for rate in (float('nan'),float('inf'),-1,0):
                with self.assertRaises(ValueError):index_archive(store,Adapter(),Budget(1,30),rate)


if __name__=='__main__':unittest.main()
