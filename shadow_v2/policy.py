"""Deterministic acceptance policy; history never establishes a current fact."""
from datetime import datetime, timedelta
from pathlib import Path
import time,math,tempfile

AREAS = ('macro','ChinaHKpolicy','AIsemis','healthcare','consumer','industrialenergycommodities','companyannouncements','calendarIPOindex')
DEFAULT_AREA_ORDER=AREAS
VERSION = 'evidence-policy-1'

class BudgetExceeded(RuntimeError): pass

class Budget:
    def __init__(self, dollars=2.0, seconds=1320):
        if not math.isfinite(float(dollars)) or not math.isfinite(float(seconds)) or dollars<0 or seconds<0:raise ValueError('invalid_budget')
        self.limit=float(dollars); self.deadline=time.monotonic()+min(float(seconds),1320)
        self.spent=0.; self.reserved=0.; self.calls=[]
    def reserve(self, name, maximum):
        if time.monotonic() >= self.deadline: raise BudgetExceeded('deadline_exceeded')
        if self.spent+self.reserved+maximum > self.limit: raise BudgetExceeded('cost_limit')
        self.reserved += maximum
        return (name, maximum)
    def settle(self, reservation, actual, usage=None):
        name, maximum=reservation
        self.reserved -= maximum; self.spent += actual
        self.calls.append({'name':name,'reserved_usd':maximum,'estimated_usd':actual,'actual_invoice_usd':None,'usage':usage or {}})
        if actual > maximum or self.spent > self.limit: raise BudgetExceeded('cost_limit')
    def remaining_seconds(self):
        left=self.deadline-time.monotonic()
        if left <= 0: raise BudgetExceeded('deadline_exceeded')
        return min(left,90)

def private_path(value):
    p=Path(value).expanduser().resolve()
    repo=Path(__file__).resolve().parents[1]
    if set(p.parts).intersection({'docs','memos','.git'}) or p in (Path('/'),Path.home(),Path(tempfile.gettempdir()).resolve()) or p == repo or repo in p.parents: raise ValueError('Private state must be outside repository')
    return p

def validate(cards, leads, cutoff, draft_ids, area_reports,previous_close=None):
    blockers=[]; cutoff=datetime.fromisoformat(cutoff)
    lower=datetime.fromisoformat(previous_close) if previous_close else cutoff-timedelta(days=1)
    if set(area_reports) != set(AREAS): blockers.append('incomplete_research_areas')
    for area in AREAS:
        report=area_reports.get(area,{})
        if not report.get('checked_urls') or report.get('status') != 'checked': blockers.append('source_unavailable:'+area)
    cardmap={c['id']:c for c in cards}
    if len(cardmap)!=len(cards): blockers.append('duplicate_story_identity')
    for lead in leads:
        if lead.get('excluded'):
            if not lead.get('exclusion_evidence') or not lead.get('exclusion_reason'): blockers.append('unsupported_exclusion:'+lead['id'])
        elif lead['id'] not in draft_ids: blockers.append('lost_material_lead:'+lead['id'])
    for cid in draft_ids:
        c=cardmap.get(cid,{})
        if not c.get('verified'): blockers.append('unverified_fact:'+cid)
        for field in ('url','evidence','published_at','issuer','statement','legal_stage','uncertainty'):
            if not c.get(field): blockers.append('missing_'+field+':'+cid)
        try:
            published=datetime.fromisoformat(c['published_at'])
            if published.tzinfo is None or published>cutoff or published<lower: blockers.append('invalid_freshness:'+cid)
        except (ValueError,KeyError,TypeError): blockers.append('invalid_timestamp:'+cid)
        try:
            event=datetime.fromisoformat(c['event_at'])
            new=datetime.fromisoformat(c['new_development_at'])
            if event.tzinfo is None or new.tzinfo is None or not lower<=new<=cutoff:raise ValueError('stale_development')
            if not c.get('freshness_evidence') or c['freshness_evidence'] not in c.get('evidence',''):raise ValueError('unsupported_freshness')
            if event>cutoff and not (c.get('calendar_event') is True and c.get('event_evidence') and c['event_evidence'] in c['evidence'] and c.get('event_date_label') and c['event_date_label'] in c['event_evidence'] and c.get('fact_audit',{}).get('future_event_supported') is True):raise ValueError('unsupported_future_event')
        except (ValueError,KeyError,TypeError):blockers.append('unproven_current_development:'+cid)
        if not c.get('critical_fields_verified'): blockers.append('critical_fields_unverified:'+cid)
    if not draft_ids: blockers.append('empty_candidate')
    return {'blockers':sorted(set(blockers)), 'optional_style':[],'policy_version':VERSION}
