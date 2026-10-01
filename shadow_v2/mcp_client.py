"""Actual MCP subprocess boundary, restricted environment, bounded calls."""
import asyncio,json,os,sys
from contextlib import asynccontextmanager
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from datetime import timedelta

@asynccontextmanager
async def history_session(timeout=60):
    allowed=('PATH','PYTHONPATH','V2_STORE_PATH','V2_BACKEND_URL','V2_CI_TOKEN','V2_OPENAI_API_KEY','V2_FIXTURE')
    env={k:os.environ[k] for k in allowed if k in os.environ}
    env.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false')
    params=StdioServerParameters(command=sys.executable,args=['-m','shadow_v2.mcp_server'],env=env)
    with open(os.devnull,'w') as errors:
        async with stdio_client(params,errlog=errors) as (read,write):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                yield session

async def call(session,name,args,usage_sink=None):
    result=await session.call_tool(name,args)
    if result.isError: raise RuntimeError('history_tool_failed:'+name)
    if usage_sink is not None and result.meta:usage_sink.append(result.meta)
    # MCP structuredContent wraps non-dict return values as result.
    if result.structuredContent is not None:
        data=result.structuredContent
        return data['result'] if set(data)=={'result'} else data
    texts=[c.text for c in result.content if c.type=='text']
    if not texts: return []
    if name in ('search_memo_history','check_recent_coverage'):
        values=[json.loads(x) for x in texts]
        return values[0] if len(values)==1 and isinstance(values[0],list) else values
    return json.loads(''.join(texts))

async def retrieve_async(query,timeout):
    async with asyncio.timeout(timeout):
        async with history_session(timeout) as session:
            usage=[]
            preferences=await call(session,'get_preference_profile',{'version':'latest'})
            history=await call(session,'search_memo_history',{'query':query,'limit':10},usage)
            feedback=await call(session,'get_item_feedback',{'item_ids':[x['id'] for x in history]})
            coverage=await call(session,'check_recent_coverage',{'query':query,'lookback_days':7},usage)
            return {'preferences':preferences,'history':history,'feedback':feedback,'coverage':coverage,'retrieval_usage':usage}

def retrieve(query,timeout=90): return asyncio.run(retrieve_async(query,timeout))

async def candidate_retrieval_async(cards,timeout):
    """Bounded per-candidate semantic lookup, same live MCP boundary."""
    if len(cards)>24:raise ValueError('candidate_retrieval_bound')
    async with asyncio.timeout(timeout):
        async with history_session(timeout) as session:
            results={};usage=[]
            for card in cards:
                query=(card['issuer']+' '+card['statement'])[:2000]
                results[card['id']]=await call(session,'search_memo_history',{'query':query,'tickers':card.get('tickers') or None,'limit':8},usage)
            return {'candidate_history':results,'candidate_retrieval_usage':usage}

def retrieve_candidates(cards,timeout=90):return asyncio.run(candidate_retrieval_async(cards,timeout))
