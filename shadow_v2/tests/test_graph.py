import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

class GraphTests(unittest.TestCase):
    def run_case(self,case):
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,'-m','shadow_v2.run','--fixture','--case',case,'--store',temp+'/store.sqlite','--output-dir',temp+'/runs'],capture_output=True,text=True,timeout=45)
            files=list(Path(temp+'/runs').glob('*.json'))
            self.assertEqual(len(files),1,result.stdout+result.stderr)
            data=json.loads(files[0].read_text())
            self.assertNotIn('Fixture macro issuer',result.stdout)
            self.assertEqual(len(list(Path(temp+'/runs').glob('*.checkpoint.sqlite'))),1)
            return data,result
    def test_approved_protocol_pipeline(self):
        data,r=self.run_case('approved');self.assertEqual(r.returncode,0);self.assertEqual(data['status'],'approved');self.assertTrue(data['evaluation']['fixture_only']);self.assertEqual(data['cards'][0]['area'],'macro');self.assertEqual(data['cards'][1]['area'],'ChinaHKpolicy')
    def test_rejected_persisted(self):
        data,r=self.run_case('failed');self.assertEqual(r.returncode,2);self.assertEqual(data['status'],'rejected');self.assertEqual(data['repairs'],1)
    def test_one_targeted_repair(self):
        data,r=self.run_case('repaired');self.assertEqual(data['status'],'approved');self.assertEqual(data['repairs'],1);self.assertEqual(set(data['draft_ids']),{l['id'] for l in data['leads']})
    def test_explicit_enable_required(self):
        r=subprocess.run([sys.executable,'-m','shadow_v2.run'],capture_output=True,timeout=10);self.assertNotEqual(r.returncode,0)
    def test_deadline_terminal_state_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,'-m','shadow_v2.run','--fixture','--store',temp+'/store.sqlite','--output-dir',temp+'/runs','--deadline-seconds','0'],capture_output=True,text=True,timeout=15)
            data=json.loads(next(Path(temp+'/runs').glob('*.json')).read_text())
            self.assertEqual(data['status'],'budget_exceeded');self.assertEqual(result.returncode,2)
    def test_live_disabled_failure_private(self):
        with tempfile.TemporaryDirectory() as temp:
            env=dict(os.environ);env.pop('V2_ENABLE_LIVE',None)
            result=subprocess.run([sys.executable,'-m','shadow_v2.run','--live','--store',temp+'/store.sqlite','--output-dir',temp+'/runs'],env=env,capture_output=True,text=True,timeout=15)
            data=json.loads(next(Path(temp+'/runs').glob('*.json')).read_text())
            self.assertEqual(data['status'],'failed');self.assertEqual(result.returncode,2)
    def test_fixture_preserves_v1_scripts(self):
        import hashlib
        def hashes():
            paths=[Path('requirements.txt')]
            for folder in ('scripts','prompts','memos','docs','.github/workflows'):
                paths.extend(p for p in Path(folder).rglob('*') if p.is_file() and 'v2' not in p.parts and '__pycache__' not in p.parts and not any(x in p.parts for x in ('specs','plans')) and 'v2' not in p.name)
            return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
        before=hashes();self.run_case('approved');self.assertEqual(before,hashes())
    def test_large_private_evidence_chunks_preserve_all_bytes(self):
        import base64,gzip,hashlib
        from shadow_v2.graph import persist_private_run
        class Recorder:
            def __init__(self):self.rows={}
            def save_shadow_run(self,run):
                self.assert_size(run);self.rows[run.get('id',run['run_id'])]=run
            def assert_size(self,run):
                if len(json.dumps(run).encode())>1_600_000:raise AssertionError('oversized backend request')
        store=Recorder();run={'run_id':'large','mode':'fixture','status':'rejected','source_pack':{'text':'source evidence 漢字 '*100000}}
        persist_private_run(store,run);manifest=store.rows['large']['private_evidence_manifest']
        raw=gzip.decompress(base64.b64decode(''.join(store.rows[i]['payload'] for i in manifest['parts'])))
        self.assertEqual(json.loads(raw),run);self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['sha256'])
    def test_checkpoint_replay_preserves_cutoff_and_is_not_fresh_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            command=[sys.executable,'-m','shadow_v2.run','--fixture','--store',temp+'/store.sqlite','--output-dir',temp+'/runs']
            first=subprocess.run(command,capture_output=True,text=True,timeout=30)
            original=json.loads(next(Path(temp+'/runs').glob('*.json')).read_text())
            replay=subprocess.run(command+['--resume',original['run_id']],capture_output=True,text=True,timeout=15)
            data=json.loads(next(Path(temp+'/runs').glob('*.replay.json')).read_text())
            self.assertEqual(replay.returncode,0,replay.stdout+replay.stderr)
            self.assertEqual(data['cutoff'],original['cutoff']);self.assertEqual(data['status'],'replayed');self.assertFalse(data['evaluation']['live_acceptance_proven'])
    def test_partial_quote_cannot_approve_invented_draft_number(self):
        from unittest.mock import patch
        from shadow_v2.graph import build_graph
        from shadow_v2.policy import Budget
        from shadow_v2.research import FixtureResearch
        from shadow_v2.store import Store
        from langgraph.checkpoint.memory import InMemorySaver
        class InventedNumber(FixtureResearch):
            def draft(self,cards):
                paragraphs=super().draft(cards);paragraphs[0]['text']+=' Profit was 999 million.';return paragraphs
            def audit(self,paragraphs,cards,sources):
                audits=super().audit(paragraphs,cards,sources)
                byid={c['id']:c for c in cards}
                for a in audits['audits']:
                    c=byid[a['id']];a['checks']=[{'claim':'all claims','source_url':c['url'],'quote':c['statement'],'verdict':'supported'}]
                return audits
            def repair(self,paragraphs,*args):return paragraphs
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp+'/store.sqlite')
            with patch.dict(os.environ,{'V2_RATE_CARD':'{"embedding_per_million":1}'}),patch('shadow_v2.graph.retrieve',return_value={}),patch('shadow_v2.graph.retrieve_candidates',return_value={}):
                graph=build_graph(store,InventedNumber(),Budget(),InMemorySaver())
                result=graph.invoke({'run_id':'number-test','mode':'live'},config={'configurable':{'thread_id':'number-test'},'recursion_limit':32})
            store.close()
            self.assertEqual(result['status'],'rejected');self.assertTrue(any(x.startswith('unsupported_draft_number:') for x in result['validation']['blockers']))
