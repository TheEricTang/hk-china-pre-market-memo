"""Isolated, evidence-first LangGraph. No publication operation exists here."""
import os,json,re,gzip,base64,hashlib
# Disable SDK ambient tracing before importing graph libraries/private data.
os.environ['LANGCHAIN_TRACING_V2']='false'
os.environ['LANGSMITH_TRACING']='false'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import TypedDict, Any
from langgraph.graph import StateGraph,START,END
from .policy import validate, BudgetExceeded, DEFAULT_AREA_ORDER
from .mcp_client import retrieve,retrieve_candidates

VERSIONS={'graph':'shadow-2.2','prompt':'evidence-english-audited-1','retrieval':'mcp-history-2-targeted','embedding':'text-embedding-3-small:v1'}

class RunState(TypedDict,total=False):
    run_id:str; target_reviewer:str; mode:str; status:str; cutoff:str; versions:dict; previous_edition:dict|None
    preferences:dict; history:list; feedback:dict; selection_signals:dict; coverage:list; cards:list; leads:list
    area_reports:dict; ordered_ids:list; draft_ids:list; markdown:str; validation:dict
    repairs:int; error_code:str; evaluation:dict; accounting:dict; research_started_at:str; previous_hk_close:str; close_convention:str; source_pack:dict; paragraphs:list; draft_audit:dict; ranking:dict; repaired_paragraphs:list; retrieval_usage:list; candidate_history:dict; candidate_retrieval_usage:list


def preference_score(card,history):
    """Explicit labels dominate; current selections are capped weak positive evidence."""
    terms=set(card.get('topics',[])+card.get('tickers',[])+[card['issuer']])
    explicit=0.;matches=[];weak=0.;negative=False;seen=set()
    for old in history:
        if old['id'] in seen:continue
        seen.add(old['id'])
        common=terms.intersection(old.get('topics',[])+old.get('tickers',[])+old.get('companies',[]))
        if not common:continue
        similarity=max(0.,min(1.,float(old.get('similarity',0))))
        label=old.get('label','unlabeled')
        contribution=similarity*({'used':.25,'not_relevant':-.25}.get(label,0))
        explicit+=contribution
        negative=negative or label=='not_relevant'
        selection=old.get('selection_signal',{})
        position=selection.get('position')
        selected=selection.get('selected') is True and isinstance(position,int) and not isinstance(position,bool) and position>=0
        # One snapshot signal per item, independent of click/reviewer counts.
        candidate_weak=.05*similarity/(1+position) if selected and label=='unlabeled' else 0.
        weak=max(weak,candidate_weak)
        matches.append({'item_id':old['id'],'label':label,'contribution':contribution,'selected':selected,'selection_position':position if selected else None,'weak_selection_candidate':candidate_weak})
    # No weak selection may offset explicit not-relevant evidence.
    weak=0. if negative else min(.05,weak)
    return {'score':max(-1.,min(1.,explicit))+weak,'explicit_feedback_matches':matches,'weak_selection_contribution':weak,'selection_suppressed_by_not_relevant':negative}

def persist_private_run(store,run):
    """Keep every evidence byte private while respecting the Edge 2 MB request cap."""
    raw=json.dumps(run,ensure_ascii=True).encode()
    if len(raw)<=1_500_000:
        store.save_shadow_run(run)
        return
    encoded=base64.b64encode(gzip.compress(raw)).decode('ascii')
    parts=[encoded[n:n+500_000] for n in range(0,len(encoded),500_000)]
    if len(parts)>32:raise ValueError('private_evidence_storage_bound')
    ids=[]
    for i,payload in enumerate(parts):
        part_id=run['run_id']+':evidence:'+str(i)
        store.save_shadow_run({'id':part_id,'run_id':part_id,'parent_run_id':run['run_id'],'status':'private_evidence_part','part':i,'encoding':'gzip+base64-json','payload':payload})
        ids.append(part_id)
    summary={key:run[key] for key in ('run_id','mode','target_reviewer','status','cutoff','versions','repairs','error_code','evaluation','accounting','validation') if key in run}
    summary['private_evidence_manifest']={'encoding':'gzip+base64-json','parts':ids,'sha256':hashlib.sha256(raw).hexdigest(),'uncompressed_bytes':len(raw)}
    store.save_shadow_run(summary)


def build_graph(store,research,budget,checkpointer,fixture_case=None):
    def safe(name,fn):
        def run(state):
            if state.get('status') in ('failed','budget_exceeded'): return {}
            try:
                budget.remaining_seconds()
                return fn(state)
            except BudgetExceeded as e: return {'status':'budget_exceeded','error_code':str(e)}
            except Exception: return {'status':'failed','error_code':name+'_failed'}
        return run
    def snapshot(s):
        stamp=datetime.now(ZoneInfo('Asia/Hong_Kong'))
        now=stamp.isoformat()
        from .calendar import previous_continuous_close
        close=previous_continuous_close(stamp).isoformat()
        return {'status':'running','target_reviewer':os.environ.get('V2_TARGET_REVIEWER','fixture-reviewer' if s['mode']=='fixture' else ''),'cutoff':now,'research_started_at':now,'previous_hk_close':close,'close_convention':'previous_hk_continuous_session_end','versions':dict(VERSIONS,model=getattr(research,'model','fixture')),'previous_edition':store.latest_edition(),'repairs':0}
    def load_preferences(s):
        # Retrieval through MCP is the sole history/preferences boundary.
        return {'preferences':{},'history':[],'feedback':{},'coverage':[]}
    def retrieve_node(s):
        price=0 if s['mode']=='fixture' else float(json.loads(os.environ['V2_RATE_CARD'])['embedding_per_million'])
        if s['mode']!='fixture' and price<=0:raise ValueError('embedding_rate_required')
        reservation=budget.reserve('mcp_history_embedding',4000*price/1e6)
        result=retrieve('Hong Kong morning market material company and policy developments',budget.remaining_seconds())
        tokens=sum(x.get('embedding_usage',{}).get('input_tokens',0) for x in result.get('retrieval_usage',[]))
        budget.settle(reservation,tokens*price/1e6,{'input_tokens':tokens,'embedding_calls':2,'usd_basis':'configured_rate_card_estimate','actual_invoice_usd':None})
        return result
    def research_node(s):
        cutoff=datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat()
        research.previous_close=s['previous_hk_close']
        return dict(research.discover(cutoff),cutoff=cutoff,research_started_at=cutoff)
    def generate(s):
        return {'cards':research.verify(s['cards'],s['source_pack'])}
    def retrieve_candidate_node(s):
        price=0 if s['mode']=='fixture' else float(json.loads(os.environ['V2_RATE_CARD'])['embedding_per_million'])
        cards=s['cards']
        if len(cards)>24:raise ValueError('candidate_retrieval_bound')
        reservation=budget.reserve('candidate_history_embedding',len(cards)*8000*price/1e6)
        result=retrieve_candidates(cards,budget.remaining_seconds())
        tokens=sum(x.get('embedding_usage',{}).get('input_tokens',0) for x in result.get('candidate_retrieval_usage',[]))
        budget.settle(reservation,tokens*price/1e6,{'input_tokens':tokens,'embedding_calls':len(cards),'usd_basis':'configured_rate_card_estimate','actual_invoice_usd':None})
        return result
    def rank(s):
        # Exact current-source duplicates reconcile to one canonical story with evidence.
        canonical={};cards=[];leads=[dict(x) for x in s['leads']];ranking={}
        for card in s['cards']:
            key=(card['issuer'],card['statement'],card['legal_stage'])
            if key in canonical and card.get('verified') and canonical[key].get('verified'):
                target=canonical[key]
                if card['id']!=target['id']:
                    for lead in leads:
                        if lead['id']==card['id']:
                            lead.update(excluded=True,exclusion_reason='Exact same factual development',exclusion_evidence={'canonical_id':target['id'],'source_url':card['url'],'statement':card['statement']})
                continue
            canonical[key]=card;cards.append(card)
        areas=s.get('preferences',{}).get('area_order',[]) if s.get('preferences',{}).get('approved_for_experiment') is True else []
        areas=areas if isinstance(areas,list) else []
        areas=list(dict.fromkeys([a for a in areas if a in DEFAULT_AREA_ORDER]+list(DEFAULT_AREA_ORDER)))
        for card in cards:
            preference=preference_score(card,s.get('candidate_history',{}).get(card['id'],[]))
            duplicate_history=any(card['statement'].strip()==old.get('body','').strip() for old in s.get('coverage',[]))
            ranking[card['id']]=dict(preference,score=preference['score']-(.2 if duplicate_history else 0),recent_exact_coverage=duplicate_history)
        cards.sort(key=lambda c:(areas.index(c['area']) if c['area'] in areas else len(areas),-ranking[c['id']]['score'],c['id']))
        return {'cards':cards,'leads':leads,'ordered_ids':[c['id'] for c in cards],'ranking':ranking}
    def draft(s):
        verified=[c for c in s['cards'] if c.get('verified')]
        paragraphs=s.get('repaired_paragraphs') if s['repairs'] else research.draft(verified)
        if paragraphs is None:paragraphs=research.draft(verified)
        if fixture_case=='repaired' and s['repairs']==0:paragraphs=paragraphs[1:]
        ids=[p.get('id','') for p in paragraphs]
        title='OFFLINE FIXTURE — NOT LIVE RESEARCH' if s['mode']=='fixture' else 'PRIVATE SHADOW — NOT FOR PUBLICATION'
        lines=[f'# {title}',f"Research cutoff: {s['cutoff']} (Asia/Hong_Kong)",'']
        byid={c['id']:c for c in s['cards']}
        for paragraph in paragraphs:
            c=byid.get(paragraph.get('id'),{})
            lines += [f"**{paragraph.get('headline','')}**: {paragraph.get('text','')} ([Source]({c.get('url','')}))",'']
        return {'paragraphs':paragraphs,'draft_ids':ids,'markdown':'\n'.join(lines)}
    def validate_node(s):
        result=validate(s['cards'],s['leads'],s['cutoff'],s['draft_ids'],s['area_reports'],s['previous_hk_close'])
        audit=research.audit(s['paragraphs'],s['cards'],s['source_pack'])
        byid={a['id']:a for a in audit.get('audits',[])}
        if len(s['draft_ids'])!=len(set(s['draft_ids'])):result['blockers'].append('duplicate_draft_identity')
        for cid in s['draft_ids']:
            a=byid.get(cid,{})
            if s['mode']!='fixture':
                card=next((c for c in s['cards'] if c['id']==cid),{})
                source=s['source_pack'].get(card.get('url'),{})
                checks=a.get('checks',[])
                if not checks or any(x.get('verdict')!='supported' or x.get('source_url')!=card.get('url') or not x.get('quote') or ' '.join(x['quote'].split()) not in ' '.join(source.get('text','').split()) for x in checks):
                    result['blockers'].append('unproven_draft_audit:'+cid)
                paragraph=next((p for p in s['paragraphs'] if p.get('id')==cid),{})
                numbers=set(re.findall(r'\d+(?:[.,]\d+)*',paragraph.get('headline','')+' '+paragraph.get('text','')))
                source_numbers=set(re.findall(r'\d+(?:[.,]\d+)*',card.get('statement','')+' '+card.get('evidence','')))
                if not numbers.issubset(source_numbers):result['blockers'].append('unsupported_draft_number:'+cid)
            if not all(a.get(k) is True for k in ('passed','all_claims_supported','is_english')) or a.get('blocking_codes'):
                result['blockers'].append('unsupported_draft_claim:'+cid)
        result['optional_style']=audit.get('optional_style',[])
        result['blockers']=sorted(set(result['blockers']))
        return {'validation':result,'draft_audit':audit}
    def route(s):
        if s.get('status') in ('failed','budget_exceeded'): return 'evaluate'
        if s['validation']['blockers'] and s['repairs']<1: return 'repair'
        return 'evaluate'
    def repair(s):
        paragraphs=research.repair(s.get('paragraphs',[]),[c for c in s['cards'] if c.get('verified')],s['source_pack'],s['validation'])
        return {'repairs':1,'repaired_paragraphs':paragraphs}
    def evaluate(s):
        status=s.get('status')
        if status not in ('failed','budget_exceeded'): status='rejected' if s.get('validation',{}).get('blockers') else 'approved'
        return {'status':status,'evaluation':{'fixture_only':s['mode']=='fixture','live_acceptance_proven':False,'policy_passed':status=='approved','source_backed_card_count':sum(bool(c.get('verified')) for c in s.get('cards',[])),'discovered_lead_count':len(s.get('leads',[])),'retained_lead_count':sum(l['id'] in s.get('draft_ids',[]) for l in s.get('leads',[])),'evidence_excluded_lead_count':sum(bool(l.get('excluded')) for l in s.get('leads',[])),'unresolved_lead_count':sum(not l.get('excluded') and l['id'] not in s.get('draft_ids',[]) for l in s.get('leads',[])),'v1_item_count':len((s.get('previous_edition') or {}).get('items',[])),'v1_edition_date':(s.get('previous_edition') or {}).get('edition_date'),'adoption_rate':None,'reviewer_quality_score':None,'v1_vs_v2_quality_delta':None},'accounting':{'estimated_spent_usd':budget.spent,'actual_invoice_usd':None,'reserved_usd':budget.reserved,'calls':budget.calls}}
    def persist(s):
        # Intentionally not wrapped: a persistence failure must reach CLI nonzero.
        persist_private_run(store,dict(s))
        return {}
    graph=StateGraph(RunState)
    nodes={'snapshot':snapshot,'load_preferences':load_preferences,'retrieve':retrieve_node,'research':research_node,'generate':generate,'retrieve_candidates':retrieve_candidate_node,'rank':rank,'draft':draft,'validate':validate_node,'repair':repair}
    for name,fn in nodes.items(): graph.add_node(name,safe(name,fn))
    graph.add_node('evaluate',evaluate); graph.add_node('persist',persist)
    chain=['snapshot','load_preferences','retrieve','research','generate','retrieve_candidates','rank','draft','validate']
    graph.add_edge(START,chain[0])
    for a,b in zip(chain,chain[1:]): graph.add_edge(a,b)
    graph.add_conditional_edges('validate',route,{'repair':'repair','evaluate':'evaluate'})
    graph.add_edge('repair','draft'); graph.add_edge('evaluate','persist'); graph.add_edge('persist',END)
    return graph.compile(checkpointer=checkpointer)
