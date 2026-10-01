"""Four read-only tools. Launch with python -m shadow_v2.mcp_server."""
import os, hashlib, math, json
from contextlib import contextmanager
from mcp.types import CallToolResult, TextContent
from datetime import datetime,timedelta,timezone
from mcp.server.fastmcp import FastMCP
from .store import Store
from .supabase_store import SupabaseStore
from .policy import private_path

server=FastMCP('hk-shadow-v2-history',log_level='ERROR')

@contextmanager
def backend():
    store=Store(str(private_path(os.environ['V2_STORE_PATH']))) if os.getenv('V2_STORE_PATH') else SupabaseStore(os.environ['V2_BACKEND_URL'],os.environ['V2_CI_TOKEN'])
    try:yield store
    finally:
        if hasattr(store,'close'):store.close()

def embed(query):
    if os.getenv('V2_FIXTURE')=='1':
        values=[x/255 for x in hashlib.sha256(query.encode()).digest()]; norm=math.sqrt(sum(x*x for x in values))
        return [x/norm for x in values], 'fixture-sha256','fixture-1',{'input_tokens':0,'total_tokens':0,'fixture_only':True}
    from .embeddings import OpenAIEmbeddingAdapter
    from openai import OpenAI
    adapter=OpenAIEmbeddingAdapter(client=OpenAI(api_key=os.environ['V2_OPENAI_API_KEY'],timeout=30,max_retries=0))
    vector=adapter.embed(query)
    return vector,adapter.model,adapter.version,adapter.last_usage

@server.tool()
def search_memo_history(query:str,date_from:str|None=None,date_to:str|None=None,tickers:list[str]|None=None,topics:list[str]|None=None,limit:int=10)->CallToolResult:
    """Historical preference/duplicate context only; never evidence for current facts."""
    if not query or len(query)>2000: raise ValueError('query_length')
    vector,model,version,usage=embed(query)
    with backend() as store:
        data=store.search_history(vector,model,version,date_from=date_from,date_to=date_to,tickers=tickers,topics=topics,limit=max(1,min(limit,20)))
    return CallToolResult(content=[TextContent(type='text',text=json.dumps(data))],structuredContent={'result':data},_meta={'embedding_usage':usage,'model':model,'version':version})

@server.tool()
def get_preference_profile(version:str='latest')->dict:
    """Read a versioned preference profile."""
    with backend() as store:return store.get_preference_profile(version)

@server.tool()
def get_item_feedback(item_ids:list[str])->dict:
    """Read explicit labels; unknown is unlabeled."""
    if len(item_ids)>100: raise ValueError('too_many_items')
    with backend() as store:return store.get_item_feedback(item_ids)

@server.tool()
def check_recent_coverage(query:str,lookback_days:int=7)->CallToolResult:
    """Find recent historical coverage, without establishing current facts."""
    start=(datetime.now(timezone.utc)-timedelta(days=max(1,min(lookback_days,90)))).date().isoformat()
    return search_memo_history(query,date_from=start)

if __name__=='__main__': server.run(transport='stdio')
