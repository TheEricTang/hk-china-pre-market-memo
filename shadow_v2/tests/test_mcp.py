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
            with patch.dict(os.environ,{'V2_STORE_PATH':path,'V2_FIXTURE':'1'}): asyncio.run(check())
