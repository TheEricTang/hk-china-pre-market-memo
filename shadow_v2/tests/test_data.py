import json
import tempfile
import unittest
import uuid
from pathlib import Path
from shadow_v2.models import parse_edition
from shadow_v2.store import Store
from shadow_v2.embeddings import OpenAIEmbeddingAdapter
from shadow_v2.supabase_store import SupabaseStore


class DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'private.db')
        self.store=Store(self.path)
        self.edition=parse_edition('- **Tencent:** Tencent (700 HK) buyback. [source](https://example.com/a)\n\n- **Other:** news.','2026-09-30')
        self.store.register_edition(self.edition)
        self.item=self.edition['items'][0]['id']
    def tearDown(self): self.store.close(); self.tmp.cleanup()
    def feedback(self,label,event=None,**kwargs):
        return self.store.add_feedback('alice',self.item,label,event or str(uuid.uuid4()),kwargs.get('edition_id',self.edition['id']))
    def test_stability_revisions_unknown_metadata(self):
        revised=parse_edition('- **Other:** news.\n\n- **Tencent:** Tencent (700 HK) buyback. [source](https://example.com/a)','2026-09-30','rev2')
        self.assertEqual(self.item,revised['items'][1]['id'])
        self.assertNotEqual(self.edition['id'],revised['id'])
        self.assertEqual(self.edition['research_cutoff'],'')
        self.store.register_edition(revised)
        self.assertEqual(self.store.latest_edition()['id'],revised['id'])
    def test_idempotency_undo_conflict_and_server_order(self):
        event=str(uuid.uuid4()); self.feedback('used',event); self.feedback('used',event)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0],1)
        with self.assertRaises(ValueError): self.feedback('cleared',event)
        self.feedback('not_relevant'); self.feedback('cleared')
        self.assertEqual(self.store.get_item_feedback([self.item]),{self.item:'unlabeled'})
        with self.assertRaises(ValueError): self.feedback('used',edition_id='bad')
    def test_tokens_are_hashed_scoped_rotatable(self):
        token=self.store.create_reviewer_token('alice')
        self.assertEqual(self.store.authenticate(token),'alice')
        self.assertIsNone(self.store.authenticate(token,'ci'))
        self.assertNotIn(token,Path(self.path).read_bytes().decode('latin1'))
        replacement=self.store.rotate_token(token)
        self.assertIsNone(self.store.authenticate(token))
        self.assertEqual(self.store.authenticate(replacement),'alice')
        self.store.revoke_token(replacement)
        self.assertIsNone(self.store.authenticate(replacement))
    def test_unknown_is_not_negative_and_reviewer_isolation(self):
        self.assertEqual(self.store.get_item_feedback([self.item])[self.item],'unlabeled')
        self.feedback('used')
        self.assertEqual(self.store.get_item_feedback([self.item],'bob')[self.item],'unlabeled')
    def test_rate_limit_retry_allowed(self):
        event=str(uuid.uuid4()); self.feedback('used',event)
        for _ in range(59): self.feedback('used')
        self.feedback('used',event)
        with self.assertRaisesRegex(ValueError,'rate'): self.feedback('used')
    def test_vector_isolation_filters_stale_hash(self):
        self.store.add_embedding(self.item,[1.,0.],'fixture','v1')
        self.assertEqual(self.store.search_history([1.,0.],'fixture','v2'),[])
        result=self.store.search_history([1.,0.],'fixture','v1',tickers=['700 HK'])
        self.assertEqual(result[0]['id'],self.item)
        self.assertEqual(result[0]['label'],'unlabeled')
        self.assertTrue(result[0]['history_only'])
        self.assertEqual(self.store.search_history([1.,0.],'fixture','v1',date_from='2026-10-01'),[])
        self.assertEqual(self.store.search_history([1.,0.],'fixture','v1',topics=['missing']),[])
        self.store.db.execute("UPDATE embeddings SET body_hash='stale'")
        self.assertEqual(self.store.search_history([1.,0.],'fixture','v1'),[])
        for vector in ([],[0.,0.],[float('nan')],[True]):
            with self.assertRaises(ValueError): self.store.add_embedding(self.item,vector,'fixture','v1')
    def test_preferences_explicit_approval(self):
        self.store.save_preference_profile({'version':'1','notes':'test'})
        self.assertFalse(self.store.get_preference_profile()['approved_for_experiment'])
        with self.assertRaises(Exception): self.store.save_preference_profile({'version':'1'})
    def test_embedding_adapter_real_contract_with_mock_transport(self):
        class Embeddings:
            def create(self,**kwargs):
                self.kwargs=kwargs
                from types import SimpleNamespace
                return SimpleNamespace(data=[SimpleNamespace(embedding=[1.]*1536)])
        from types import SimpleNamespace
        client=SimpleNamespace(embeddings=Embeddings())
        adapter=OpenAIEmbeddingAdapter(client=client,version='v3')
        self.assertEqual(len(adapter.embed('public memo')),1536)
        self.assertEqual(client.embeddings.kwargs['dimensions'],1536)
    def test_tags_and_invalid_ranges_conflicting_edition(self):
        tagged=parse_edition('- **Nvidia earnings:** Nvidia (NASDAQ: NVDA) semiconductor earnings.','2026-09-30')
        self.assertEqual(tagged['items'][0]['tickers'],['NVDA'])
        self.assertIn('earnings',tagged['items'][0]['topics'])
        self.assertIn('technology',tagged['items'][0]['sectors'])
        self.assertEqual(tagged['items'][0]['companies'],['Nvidia'])
        corrupted=dict(self.edition, research_cutoff='different')
        with self.assertRaisesRegex(ValueError,'immutable edition'): self.store.register_edition(corrupted)
        with self.assertRaises(ValueError): self.store.search_history([1.],'fixture','v1',date_from='bad')
        with self.assertRaises(ValueError): self.store.search_history([1.],'fixture','v1',date_from='2026-10-01',date_to='2026-09-01')

    def test_whitespace_revision_preserves_raw_edition_body(self):
        first=parse_edition('- **Story:** Same fact.','2026-09-29','first')
        second=parse_edition('- **Story:** Same  fact.','2026-09-29','second')
        self.assertEqual(first['items'][0]['id'],second['items'][0]['id'])
        self.store.register_edition(first)
        self.store.register_edition(second)
        actual=json.loads(self.store.db.execute('SELECT payload FROM editions WHERE id=?',(second['id'],)).fetchone()[0])
        self.assertEqual(actual['items'][0]['body'],'**Story:** Same  fact.')
        self.assertEqual(self.store.get_item(first['items'][0]['id'])['body'],'**Story:** Same fact.')

    def test_ingest_refuses_all_repository_paths_and_allows_private_store(self):
        from unittest.mock import patch
        from shadow_v2.ingest import main
        from shadow_v2.paths import REPOSITORY
        archive=Path(self.tmp.name)/'archive';archive.mkdir()
        (archive/'memo-2026-09-30.md').write_text('- **Story:** Same fact.')
        for path in (REPOSITORY/'state.db',REPOSITORY/'docs/v2/state.db'):
            with patch('sys.argv',['ingest','--public-archive',str(archive),'--store',str(path)]):
                with self.assertRaisesRegex(ValueError,'outside the public repository'): main()
            self.assertFalse(path.exists())
        destination=Path(self.tmp.name)/'ingested.db'
        with patch('sys.argv',['ingest','--public-archive',str(archive),'--store',str(destination)]): main()
        with Store(str(destination)) as imported: self.assertEqual(len(imported.latest_edition()['items']),1)

    def test_nonfinite_zero_and_overflow_vectors_rejected(self):
        for vector in ([0.,0.],[float('inf')],[float('-inf')],[float('nan')],[1e30],[1e-30]):
            with self.assertRaises(ValueError): self.store.add_embedding(self.item,vector,'fixture','v1')
            with self.assertRaises(ValueError): self.store.search_history(vector,'fixture','v1')

    def test_normalized_boundary_vectors_have_finite_similarity(self):
        import math
        for magnitude in (1e17,1e18,1e19,1e20,1e-20,1e-21):
            vector=[magnitude]*1536
            self.store.add_embedding(self.item,vector,'fixture','v1')
            stored=json.loads(self.store.db.execute('SELECT vector FROM embeddings WHERE item_id=?',(self.item,)).fetchone()[0])
            self.assertAlmostEqual(sum(x*x for x in stored),1)
            result=self.store.search_history(vector,'fixture','v1')[0]
            self.assertTrue(math.isfinite(result['similarity']))
            self.assertTrue(math.isfinite(result['retrieval_score']))
            self.assertAlmostEqual(result['similarity'],1)

    def test_has_embedding_requires_exact_current_hash_and_version(self):
        self.assertFalse(self.store.has_embedding(self.item,'fixture','v1'))
        self.store.add_embedding(self.item,[1,0],'fixture','v1')
        self.assertTrue(self.store.has_embedding(self.item,'fixture','v1'))
        self.assertFalse(self.store.has_embedding(self.item,'fixture','v2'))
        self.assertFalse(self.store.has_embedding(self.item,'other','v1'))
        self.assertFalse(self.store.has_embedding('missing','fixture','v1'))
        self.store.db.execute("UPDATE embeddings SET body_hash='stale'")
        self.assertFalse(self.store.has_embedding(self.item,'fixture','v1'))

    def test_cloud_archive_import_is_bounded_deterministic_and_unlabeled(self):
        import os
        from unittest.mock import patch
        from shadow_v2.ingest import main
        archive=Path(self.tmp.name)/'cloud-archive';archive.mkdir()
        for day in ('28','30','29'):
            (archive/f'memo-2026-09-{day}.md').write_text(f'- **Story {day}:** Public fact.')
        (archive/'private.eml').write_text('ignored non-public format')
        endpoint='https://dedicated.example/functions/v1/memo-v2'
        args=['ingest','--public-archive',str(archive),'--cloud','--max-editions','2','--source-version','archive-test']
        # Real parsing and real SQLite persistence behind a mocked cloud boundary.
        with patch.dict(os.environ,{'V2_BACKEND_URL':endpoint,'V2_CI_TOKEN':'fixture-ci-token'}), patch('shadow_v2.ingest.SupabaseStore',return_value=self.store) as backend, patch('sys.argv',args):
            main()
            backend.assert_called_once_with(endpoint,'fixture-ci-token')
        rows=self.store.db.execute('SELECT payload FROM editions WHERE id<>? ORDER BY seq',(self.edition['id'],)).fetchall()
        self.assertEqual([json.loads(row[0])['edition_date'] for row in rows],['2026-09-29','2026-09-30'])
        self.assertTrue(all(json.loads(row[0])['source_version']=='archive-test' for row in rows))
        self.assertTrue(all(json.loads(row[0])['research_cutoff']=='' for row in rows))
        for row in rows:
            ids=[item['id'] for item in json.loads(row[0])['items']]
            self.assertTrue(all(label=='unlabeled' for label in self.store.get_item_feedback(ids).values()))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM embeddings').fetchone()[0],0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0],0)

    def test_ingest_backend_selection_limits_and_invalid_batch_do_not_write(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        from io import StringIO
        from shadow_v2.ingest import main
        archive=Path(self.tmp.name)/'bad-archive';archive.mkdir()
        base=['ingest','--public-archive',str(archive)]
        bad_args=[base,base+['--cloud','--store',str(Path(self.tmp.name)/'other.db')],base+['--cloud','--max-editions','0'],base+['--cloud','--max-editions','1001']]
        for argv in bad_args:
            with patch('sys.argv',argv), patch('shadow_v2.ingest.SupabaseStore') as backend, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit): main()
                backend.assert_not_called()
        (archive/'memo-2026-09-29.md').write_text('- **Good:** Public fact.')
        (archive/'memo-2026-09-30.md').write_text('Invalid empty edition')
        with patch('sys.argv',base+['--cloud']), patch('shadow_v2.ingest.SupabaseStore') as backend:
            with self.assertRaisesRegex(ValueError,'no items'): main()
            backend.assert_not_called()

    def test_backend_https_only(self):
        for url in ('http://x','https://user:pass@x','https://x#token'):
            with self.assertRaises(ValueError): SupabaseStore(url,'secret')

if __name__=='__main__': unittest.main()
