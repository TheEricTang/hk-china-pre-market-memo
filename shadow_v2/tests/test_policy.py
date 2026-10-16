import unittest
from datetime import datetime,timezone
from shadow_v2.policy import Budget,BudgetExceeded,validate,private_path
from shadow_v2.research import FixtureResearch,verify_card

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.cutoff=datetime.now(timezone.utc).isoformat();self.data=FixtureResearch().discover(self.cutoff); self.data['cards']=FixtureResearch().verify(self.data['cards'],self.data['source_pack'])
    def check(self):
        d=self.data
        return validate(d['cards'],d['leads'],self.cutoff,[c['id'] for c in d['cards']],d['area_reports'])['blockers']
    def test_valid(self): self.assertEqual(self.check(),[])
    def test_unverified(self):
        self.data['cards'][0]['verified']=False;self.assertTrue(self.check())
    def test_cutoff(self):
        self.data['cards'][0]['published_at']='2099-01-01T00:00:00+00:00';self.assertTrue(self.check())
    def test_provenance(self):
        del self.data['cards'][0]['evidence'];self.assertTrue(self.check())
    def test_lead_retention(self):
        self.data['leads'].append({'id':'missing'});self.assertIn('lost_material_lead:missing',self.check())
    def test_budget_reserves_worst_case(self):
        b=Budget(.1); b.reserve('a',.08)
        with self.assertRaises(BudgetExceeded): b.reserve('b',.03)
    def test_deadline(self):
        with self.assertRaises(BudgetExceeded): Budget(seconds=0).reserve('a',0)
    def test_repo_rejected(self):
        with self.assertRaises(ValueError): private_path(__file__)
    def test_style_is_optional(self):
        d=self.data;r=validate(d['cards'],d['leads'],self.cutoff,[c['id'] for c in d['cards']],d['area_reports']);r['optional_style'].append('shorter headline');self.assertEqual(r['blockers'],[])
    def test_previous_close_rejects_old_publication(self):
        d=self.data;d['cards'][0]['published_at']='2020-01-01T12:00:00+00:00'
        self.assertTrue(self.check())
    def test_undocumented_future_event_blocks(self):
        self.data['cards'][0]['event_at']='2099-01-01T00:00:00+00:00'
        self.assertTrue(self.check())
    def test_calendar_exception_requires_evidence(self):
        c=self.data['cards'][0];c['event_at']='2099-01-01T00:00:00+00:00';c['calendar_event']=True;c['evidence']+=' Meeting on 1 January 2099.';c['event_evidence']='Meeting on 1 January 2099.';c['event_date_label']='1 January 2099';c['fact_audit']['future_event_supported']=True
        self.assertEqual(self.check(),[])
    def test_fresh_article_old_unchanged_event_blocks(self):
        c=self.data['cards'][0];c['event_at']='2020-01-01T12:00:00+00:00';c['new_development_at']=c['event_at']
        self.assertTrue(self.check())
    def test_invalid_budget(self):
        with self.assertRaises(ValueError):Budget(float('nan'))
    def test_private_path_public_other_checkout_blocked(self):
        with self.assertRaises(ValueError):private_path('/private/tmp/other-checkout/docs/private.json')
    def test_semantic_audit_cannot_pass_without_source_spans(self):
        from shadow_v2.research import OpenAIResearch
        research=object.__new__(OpenAIResearch)
        card=self.data['cards'][0]
        flags={key:True for key in ('passed','issuer_correct','figures_units_correct','legal_stage_correct','qualifiers_preserved','publication_supported','fresh_development_supported')}
        research.call=lambda *args,**kwargs:({'audits':[dict(flags,id=card['id'],blocking_codes=[])]},[])
        result=research.verify([card],self.data['source_pack'])
        self.assertFalse(result[0]['verified'])
    def test_invented_numeric_field_not_lexically_verified(self):
        card=dict(self.data['cards'][0]);card['critical_figures']=[]
        result=verify_card(card,self.data['source_pack'][card['url']],self.cutoff)
        self.assertFalse(result['lexical_verified'])
    def test_metadata_does_not_mean_semantic_verification(self):
        card=self.data['cards'][0]
        result=verify_card(card,self.data['source_pack'][card['url']],self.cutoff)
        self.assertTrue(result['lexical_verified']);self.assertFalse(result['verified'])
    def test_partial_discovery_survives_later_area_failure(self):
        from shadow_v2.research import OpenAIResearch
        from unittest.mock import patch
        research=object.__new__(OpenAIResearch);research.budget=Budget()
        card=self.data['cards'][0];calls=[]
        def call(*args,**kwargs):
            if calls:raise RuntimeError('source outage')
            calls.append(True)
            return {'leads':[card]},[{'status':'completed','action':{'type':'search','sources':[{'url':card['url']}]}}]
        research.call=call
        with patch('shadow_v2.research.fetch_source',return_value=self.data['source_pack'][card['url']]):result=research.discover(self.cutoff)
        self.assertEqual(result['status'],'failed');self.assertEqual(len(result['leads']),1);self.assertEqual(len(result['source_pack']),1)
    def test_nonfinite_rate_card_rejected(self):
        from shadow_v2.research import OpenAIResearch
        rates={'model':'test','validated_at':'now','source':'operator','input_per_million':float('nan'),'output_per_million':1,'input_token_ceiling':10000,'search_per_call':1}
        with self.assertRaises(ValueError):OpenAIResearch(None,'test',Budget(),rates)
    def test_fake_semantic_quotes_do_not_validate_claim(self):
        from shadow_v2.research import OpenAIResearch
        research=object.__new__(OpenAIResearch);card=self.data['cards'][0]
        audit={key:True for key in ('passed','issuer_correct','figures_units_correct','legal_stage_correct','qualifiers_preserved','publication_supported','fresh_development_supported')}
        audit.update(id=card['id'],checks=[{'field':f,'source_url':card['url'],'quote':'nonexistent fact','verdict':'supported'} for f in ('issuer','figures_units','legal_stage','qualifiers','publication','freshness')],blocking_codes=[])
        research.call=lambda *a,**k:({'audits':[audit]},[])
        self.assertFalse(research.verify([card],self.data['source_pack'])[0]['verified'])
    def test_christmas_half_day_close(self):
        from shadow_v2.calendar import previous_continuous_close
        self.assertEqual(previous_continuous_close(datetime.fromisoformat('2026-12-28T07:00:00+08:00')).isoformat(),'2026-12-24T12:00:00+08:00')
    def test_new_year_half_day_close(self):
        from shadow_v2.calendar import previous_continuous_close
        self.assertEqual(previous_continuous_close(datetime.fromisoformat('2027-01-04T07:00:00+08:00')).isoformat(),'2026-12-31T12:00:00+08:00')
    def test_previous_year_unknown_fails_closed(self):
        from shadow_v2.calendar import previous_continuous_close
        with self.assertRaises(ValueError):previous_continuous_close(datetime.fromisoformat('2026-01-01T07:00:00+08:00'))
