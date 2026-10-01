import asyncio,os,tempfile,unittest
from unittest.mock import patch
from shadow_v2.mcp_client import history_session,call
from shadow_v2.store import Store

class MCPTests(unittest.TestCase):
    def test_four_read_only_tools(self):
        async def check():
            async with history_session() as session:
                tools=(await session.list_tools()).tools
                self.assertEqual({t.name for t in tools},{'search_memo_history','get_preference_profile','get_item_feedback','check_recent_coverage'})
                self.assertEqual(await call(session,'get_item_feedback',{'item_ids':['unknown']}),{'unknown':'unlabeled'})
                self.assertEqual(await call(session,'search_memo_history',{'query':'test'}),[])
        with tempfile.TemporaryDirectory() as temp:
            path=temp+'/store.sqlite';store=Store(path);store.db.close()
            with patch.dict(os.environ,{'V2_STORE_PATH':path,'V2_FIXTURE':'1','V2_TARGET_REVIEWER':'reviewer'}): asyncio.run(check())
    def test_selection_metadata_is_separate_and_latest_snapshot_wins(self):
        import uuid
        from shadow_v2.models import parse_edition
        from shadow_v2.mcp_client import feedback_with_selections,candidate_retrieval_async
        with tempfile.TemporaryDirectory() as temp:
            path=temp+'/store.sqlite';store=Store(path)
            edition=parse_edition('- **Tencent:** Tencent (700 HK) update. [source](https://example.com/a)','2026-09-30')
            store.register_edition(edition);item=edition['items'][0]['id']
            store.add_selection('reviewer',edition['id'],[item],str(uuid.uuid4()))
            store.add_embedding(item,[1.0]*32,'fixture-sha256','fixture-1')
            async def check():
                async with history_session() as session:
                    labels,signals=await feedback_with_selections(session,[item,item])
                    self.assertEqual(labels[item],'unlabeled');self.assertTrue(signals[item]['selected']);self.assertEqual(signals[item]['position'],0)
                    candidates=await candidate_retrieval_async([{'id':'current','issuer':'Tencent','statement':'Tencent update','tickers':[]}],30)
                    match=candidates['candidate_history']['current'][0]
                    self.assertEqual(match['label'],'unlabeled');self.assertTrue(match['selection_signal']['selected'])
                    store.add_selection('reviewer',edition['id'],[],str(uuid.uuid4()))
                    labels,signals=await feedback_with_selections(session,[item])
                    self.assertEqual(labels[item],'unlabeled');self.assertFalse(signals[item]['selected'])
                    store.add_feedback('reviewer',item,'used',str(uuid.uuid4()),edition['id'])
                    labels,signals=await feedback_with_selections(session,[item])
                    self.assertEqual(labels[item],'used');self.assertFalse(signals[item]['selected'])
            try:
                with patch.dict(os.environ,{'V2_STORE_PATH':path,'V2_FIXTURE':'1','V2_TARGET_REVIEWER':'reviewer'}):asyncio.run(check())
            finally:store.close()
    def test_configured_reviewer_ignores_other_labels_and_selections(self):
        import uuid
        from shadow_v2.models import parse_edition
        from shadow_v2.mcp_client import candidate_retrieval_async
        from shadow_v2.graph import preference_score
        with tempfile.TemporaryDirectory() as temp:
            path=temp+'/store.sqlite';store=Store(path)
            edition=parse_edition('- **Tencent:** Tencent (700 HK) first update. [source](https://example.com/a)\n\n- **Tencent follow-up:** Tencent (700 HK) second update. [source](https://example.com/b)','2026-09-30')
            store.register_edition(edition);first,second=[i['id'] for i in edition['items']]
            store.add_feedback('target',first,'used',str(uuid.uuid4()),edition['id'])
            store.add_feedback('other',first,'not_relevant',str(uuid.uuid4()),edition['id'])
            store.add_selection('other',edition['id'],[second],str(uuid.uuid4()))
            for item in edition['items']:store.add_embedding(item['id'],[1.0]*32,'fixture-sha256','fixture-1')
            self.assertEqual(store.get_item_feedback([first])[first],'not_relevant')
            self.assertTrue(store.get_selection_signals([second])[second]['selected'])
            card={'id':'current','issuer':'Tencent','statement':'Tencent updates','tickers':['700 HK'],'topics':[]}
            async def check():
                result=await candidate_retrieval_async([card],30)
                matches=result['candidate_history']['current'];byid={m['id']:m for m in matches}
                self.assertEqual(byid[first]['label'],'used');self.assertEqual(byid[second]['label'],'unlabeled')
                self.assertFalse(byid[second]['selection_signal']['selected'])
                score=preference_score(card,matches)
                self.assertGreater(score['score'],0);self.assertEqual(score['weak_selection_contribution'],0)
                self.assertFalse(score['selection_suppressed_by_not_relevant'])
            try:
                with patch.dict(os.environ,{'V2_STORE_PATH':path,'V2_FIXTURE':'1','V2_TARGET_REVIEWER':'target'}):asyncio.run(check())
            finally:store.close()
    def test_live_feedback_requires_target_reviewer(self):
        from shadow_v2.mcp_server import target_reviewer
        with patch.dict(os.environ,{'V2_FIXTURE':'0','V2_TARGET_REVIEWER':'   '}):
            with self.assertRaisesRegex(ValueError,'target_reviewer_required'):target_reviewer()
