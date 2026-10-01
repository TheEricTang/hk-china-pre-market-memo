"""Explicit opt-in runner. All output and checkpoints remain outside the repo."""
import argparse,json,os,sys,uuid,signal,math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from .policy import Budget,private_path,BudgetExceeded

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fixture',action='store_true'); mode.add_argument('--live',action='store_true')
    backend=parser.add_mutually_exclusive_group(required=True)
    backend.add_argument('--store'); backend.add_argument('--cloud',action='store_true')
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--resume',help='Replay a saved terminal checkpoint; resume interrupted fixtures only')
    parser.add_argument('--case',choices=('approved','failed','repaired'),default='approved')
    parser.add_argument('--budget-usd',type=float,default=2.0)
    parser.add_argument('--deadline-seconds',type=float,default=1320)
    args=parser.parse_args(argv)
    os.umask(0o077)
    def deadline_signal(signum,frame):raise BudgetExceeded('deadline_exceeded')
    signal.signal(signal.SIGALRM,deadline_signal)
    os.environ['LANGCHAIN_TRACING_V2']='false'; os.environ['LANGSMITH_TRACING']='false'
    # Remote custom callbacks are not configured anywhere in this graph.
    from .store import Store
    from .supabase_store import SupabaseStore
    from .research import FixtureResearch,OpenAIResearch
    from .graph import build_graph
    from langgraph.checkpoint.sqlite import SqliteSaver
    store=None;output=None;run_id=str(uuid.uuid4())
    try:
        output=private_path(args.output_dir); output.mkdir(parents=True,exist_ok=True,mode=0o700)
        output.chmod(0o700)
        if args.store:
            path=private_path(args.store); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            os.environ['V2_STORE_PATH']=str(path); store=Store(str(path)); path.chmod(0o600)
        else:
            os.environ.pop('V2_STORE_PATH',None)
            store=SupabaseStore(os.environ['V2_BACKEND_URL'],os.environ['V2_CI_TOKEN'])
        budget=Budget(args.budget_usd,args.deadline_seconds)
        if args.deadline_seconds>0:signal.setitimer(signal.ITIMER_REAL,min(args.deadline_seconds,1320))
        if args.resume:
            run_id=str(uuid.UUID(args.resume))
            research=FixtureResearch(args.case)
            if args.fixture:os.environ['V2_FIXTURE']='1'
        elif args.fixture:
            os.environ['V2_FIXTURE']='1'; research=FixtureResearch(args.case)
        else:
            os.environ.pop('V2_FIXTURE',None)
            if os.environ.get('V2_ENABLE_LIVE')!='1': raise ValueError('live_not_enabled')
            model=os.environ.get('V2_MODEL','gpt-5.6-sol')
            rates=json.loads(os.environ['V2_RATE_CARD'])
            from openai import OpenAI
            research=OpenAIResearch(OpenAI(api_key=os.environ['V2_OPENAI_API_KEY'],max_retries=0,timeout=90),model,budget,rates)
        checkpoint=output/(run_id+'.checkpoint.sqlite')
        if args.resume and not checkpoint.is_file():raise ValueError('checkpoint_not_found')
        with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
            graph=build_graph(store,research,budget,saver,args.case if args.fixture else None)
            config={'configurable':{'thread_id':run_id},'recursion_limit':32,'callbacks':[]}
            if args.resume:
                saved=graph.get_state(config)
                result=dict(saved.values)
                if not result or result.get('mode')!=('fixture' if args.fixture else 'live'):raise ValueError('checkpoint_mode_mismatch')
                cutoff=datetime.fromisoformat(result['cutoff'])
                stale=cutoff.astimezone(ZoneInfo('Asia/Hong_Kong')).date()!=datetime.now(ZoneInfo('Asia/Hong_Kong')).date()
                if saved.next and not stale:
                    if not args.fixture:raise ValueError('live_interruption_billing_requires_reconciliation')
                    result=graph.invoke(None,config=config)
                original_status=result.get('status')
                result=dict(result,status='rejected' if stale else 'replayed',original_status=original_status)
                result['evaluation']=dict(result.get('evaluation',{}),checkpoint_replay=True,stale_checkpoint=stale,live_acceptance_proven=False)
                if stale:result['validation']={'blockers':['stale_checkpoint'],'optional_style':[]}
            else:
                result=graph.invoke({'run_id':run_id,'mode':'fixture' if args.fixture else 'live'},config=config)
        checkpoint.chmod(0o600)
        (output/(run_id+('.replay.json' if args.resume else '.json'))).write_text(json.dumps(result,ensure_ascii=False,indent=2))
        if result.get('markdown') and not args.resume: (output/(run_id+'.md')).write_text(result['markdown'])
        print(json.dumps({'status':result['status'],'mode':result['mode'],'repairs':result.get('repairs',0)}))
        return 0 if result['status'] in ('approved','replayed') else 2
    except Exception as error:
        failure={'run_id':str(uuid.uuid4()) if args.resume else run_id,'mode':'fixture' if args.fixture else 'live','status':'budget_exceeded' if isinstance(error,BudgetExceeded) else 'failed','error_code':'shadow_run_failed'}
        try:
            if output is not None and output.is_dir():(output/(failure['run_id']+'.json')).write_text(json.dumps(failure))
        except Exception:pass
        try:
            if store is not None:store.save_shadow_run(failure)
        except Exception:pass
        # No source text, credentials, addresses, backend URLs or stack traces in CI.
        print(json.dumps({'status':failure['status'],'error':'shadow_run_failed'}))
        return 2
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        if store is not None and hasattr(store,'close'):store.close()

if __name__=='__main__': sys.exit(main())
