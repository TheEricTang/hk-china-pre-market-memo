import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker, { tick } from './worker.mjs';

const env = { GITHUB_TOKEN: 'test-only', ENABLED: 'true' };
const now = new Date('2026-09-16T22:35:00Z'); // Thursday 06:35 HKT
const receipt = { editionDate: '2026-09-17', editionMode: 'preopen', qualityPassed: true,
  memoSha256: 'a'.repeat(64), researchCutoff: '2026-09-17T06:35:00+08:00', generatedAt: '2026-09-17T07:00:00+08:00' };
const page = '<h1>Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open</h1><meta name="memo-sha256" content="'+'a'.repeat(64)+'">';
function fake({ current = false, active = false, apiFailure = false } = {}) {
  const calls = [];
  return { calls, fetch: async (url, options = {}) => {
    calls.push({ url: String(url), ...options });
    if (String(url).includes('status.json')) return Response.json(current ? receipt : {});
    if (String(url).startsWith('https://theerictang.github.io/')) return new Response(current ? page : '<h1>Old memo</h1>');
    if (String(url).includes('/runs?')) return apiFailure ? new Response('', { status: 503 }) : Response.json({ workflow_runs: active ? [{ status: 'in_progress', head_branch: 'main' }] : [] });
    if (String(url).endsWith('/dispatches')) return new Response(null, { status: 204 });
    throw new Error('Unexpected destination '+url);
  }};
}

test('dispatches an automatic run at 06:35 HKT when public edition is stale', async () => {
  const f = fake(); const out = await tick(env, { now, fetchImpl: f.fetch });
  assert.equal(out.state, 'dispatched');
  const post = f.calls.find(x=>x.method==='POST');
  assert.equal(post.url, 'https://api.github.com/repos/TheEricTang/hk-china-pre-market-memo/actions/workflows/daily-memo.yml/dispatches');
  assert.deepEqual(JSON.parse(post.body), { ref: 'main', inputs: { automatic: true, generate: true, edition_mode: 'preopen' } });
});
test('does not dispatch before research window, weekends, or when disabled', async () => {
  for (const [stamp, enabled] of [['2026-09-16T22:30:00Z', 'true'], ['2026-09-18T22:35:00Z', 'true'], ['2026-09-16T22:35:00Z', 'false']]) {
    const f = fake(); const out = await tick({ ...env, ENABLED: enabled }, { now: new Date(stamp), fetchImpl:f.fetch });
    assert.equal(out.state, 'skipped'); assert.equal(f.calls.length,0);
  }
});
test('does not duplicate an active GitHub workflow', async () => {
  const f=fake({active:true}); const out=await tick(env,{now,fetchImpl:f.fetch});
  assert.equal(out.state,'running'); assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});
test('requires a live page matching its quality receipt before declaring delivered', async () => {
  const f=fake({current:true}); const out=await tick(env,{now:new Date('2026-09-16T23:05:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'delivered'); assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});
test('fails closed when workflow status cannot be read', async () => {
  const f=fake({apiFailure:true});
  await assert.rejects(tick(env,{now,fetchImpl:f.fetch}), /GitHub status/);
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});
test('flags a missed deadline even when a run is active', async () => {
  const f=fake({active:true}); const out=await tick(env,{now:new Date('2026-09-16T23:30:00Z'),fetchImpl:f.fetch});
  assert.equal(out.deadlineMissed,true); assert.equal(out.state,'running');
});
test('public HTTP endpoint cannot trigger generation', async () => {
  const response=await worker.fetch(new Request('https://scheduler.example/dispatch',{method:'POST'}),env);
  assert.equal(response.status,404);
});

test('does not trigger or report deadline failures on an HK exchange holiday', async () => {
  const f=fake(); const out=await tick(env,{now:new Date('2026-09-30T23:30:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'skipped'); assert.equal(f.calls.length,0);
});
test('keeps scheduler holidays synchronized with the production trading calendar', async () => {
  const { execFileSync } = await import('node:child_process');
  const { holidays, calendarYears } = await import('./calendar.mjs');
  const json=execFileSync('python3',['-c','import json,sys;sys.path.insert(0,"scripts");from trading_calendar import HKEX_HOLIDAYS;print(json.dumps({"years":sorted(HKEX_HOLIDAYS),"dates":sorted(set().union(*HKEX_HOLIDAYS.values()))}))'],{encoding:'utf8'});
  const actual=JSON.parse(json);
  assert.deepEqual([...holidays].sort(),actual.dates);
  assert.deepEqual([...calendarYears].sort(),actual.years);
});
test('bounds repeated dispatches when generation keeps failing', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async (url,options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[0,1,2].map(()=>({event:'workflow_dispatch',head_branch:'main',status:'completed',created_at:'2026-09-16T22:35:00Z'}))}) : original(url,options);
  const out=await tick(env,{now:new Date('2026-09-16T23:20:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'recovery_exhausted'); assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});
test('does not accept a checked receipt paired with an older page hash', async () => {
  const f=fake({current:true}); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('status.json') ? Response.json({...receipt,memoSha256:'b'.repeat(64)}) : original(url,options);
  const out=await tick(env,{now:new Date('2026-09-16T23:05:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'dispatched');
});
test('does not accept an early provisional edition as the final morning memo', async () => {
  const f=fake({current:true}); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('status.json') ? Response.json({...receipt,researchCutoff:'2026-09-17T05:30:00+08:00'}) : original(url,options);
  const out=await tick(env,{now:new Date('2026-09-16T23:05:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'dispatched');
});

test('07:40 recovery dispatch can only redeploy an approved memo without paid generation', async () => {
  const f=fake();
  const out=await tick(env,{now:new Date('2026-09-16T23:40:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'dispatched');
  assert.equal(out.deadlineMissed,true);
  assert.deepEqual(JSON.parse(f.calls.find(x=>x.method==='POST').body),
    {ref:'main',inputs:{automatic:true,generate:false,edition_mode:'preopen'}});
});

test('three earlier generation dispatches leave a separate deployment recovery allowance', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[0,1,2].map(()=>({
    event:'workflow_dispatch',head_branch:'main',status:'completed',created_at:'2026-09-16T22:35:00Z',
  }))}) : original(url,options);
  const out=await tick(env,{now:new Date('2026-09-16T23:40:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'dispatched');
  assert.equal(JSON.parse(f.calls.find(x=>x.method==='POST').body).inputs.generate,false);
});

test('deployment recovery stops after two late dispatches', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[0,1].map(()=>({
    event:'workflow_dispatch',head_branch:'main',status:'completed',created_at:'2026-09-16T23:35:00Z',
  }))}) : original(url,options);
  const out=await tick(env,{now:new Date('2026-09-16T23:50:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'recovery_exhausted');
  assert.equal(out.deadlineMissed,true);
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});

test('late recovery never duplicates an active workflow', async () => {
  const f=fake({active:true});
  const out=await tick(env,{now:new Date('2026-09-16T23:40:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'running');
  assert.equal(out.deadlineMissed,true);
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});

test('all automatic recovery dispatches stop at 08:00 HKT', async () => {
  const f=fake();
  const out=await tick(env,{now:new Date('2026-09-17T00:00:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'skipped');
  assert.equal(f.calls.length,0);
});


test('main-branch rehearsal does not suppress production or consume dispatch allowance', async () => {
  const f = fake(); const original = f.fetch;
  f.fetch = async (url, options) => String(url).includes('/runs?') ? Response.json({workflow_runs:
    [0,1,2,3].map(i => ({head_branch:'main', display_title:'Memo validation rehearsal',
      status:i===0?'in_progress':'completed', event:'workflow_dispatch', created_at:'2026-09-16T22:35:00Z'}))
  }) : original(url, options);
  const out = await tick(env, {now:new Date('2026-09-16T23:05:00Z'), fetchImpl:f.fetch});
  assert.equal(out.state, 'dispatched');
  assert.equal(f.calls.filter(x=>x.method==='POST').length, 1);
});

test('production run older than35minutes requires attention without cancellation or dispatch', async () => {
  for (const status of ['queued','in_progress','waiting']) {
    const f=fake(); const original=f.fetch;
    f.fetch=async(url, options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[{
      head_branch:'main', display_title:'Daily HK China memo', status, created_at:'2026-09-16T21:59:00Z'
    }]}) : original(url, options);
    const out=await tick(env,{now,fetchImpl:f.fetch});
    assert.equal(out.state,'stalled'); assert.equal(out.requiresAttention,true);
    assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
  }
});

test('35minute boundary remains running and a newer production run still blocks duplicates', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async(url, options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[{
    head_branch:'main', display_title:'Daily HK China memo', status:'in_progress', created_at:'2026-09-16T22:00:00Z'
  }]}) : original(url, options);
  const out=await tick(env,{now,fetchImpl:f.fetch});
  assert.equal(out.state,'running');
});

test('workflow gives rehearsals the explicit scheduler marker and preserves generation limit', async () => {
  const {readFileSync}=await import('node:fs');
  const workflow=readFileSync('.github/workflows/daily-memo.yml','utf8');
  assert.match(workflow,/run-name: .*inputs\.dry_run.*Memo validation rehearsal.*Daily HK China memo/);
  assert.match(workflow,/name: Generate and validate memo\n\s+timeout-minutes: 24/);
});

test('known early scheduled runner is not stalled merely because it waited for06:35', async () => {
  const f=fake(); const original=f.fetch;
  const run={head_branch:'main',display_title:'Daily HK China memo — early runner',
    status:'in_progress',event:'schedule',created_at:'2026-09-16T17:35:00Z'};
  f.fetch=async(url,options)=>String(url).includes('/runs?')
    ? Response.json({workflow_runs:[run]}) : original(url,options);
  const out=await tick(env,{now,fetchImpl:f.fetch});
  assert.equal(out.state,'running');
  assert.equal(run.created_at,'2026-09-16T17:35:00Z');
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});

test('early runner becomes stalled after35minutes of its eligible research window', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[{
    head_branch:'main',display_title:'Daily HK China memo — early runner',
    status:'in_progress',event:'schedule',created_at:'2026-09-16T17:35:00Z'
  }]}) : original(url,options);
  const out=await tick(env,{now:new Date('2026-09-16T23:11:00Z'),fetchImpl:f.fetch});
  assert.equal(out.state,'stalled');
  assert.equal(out.requiresAttention,true);
});

test('early marker on manual dispatch cannot hide an old stalled run', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[{
    head_branch:'main',display_title:'Daily HK China memo — early runner',
    status:'in_progress',event:'workflow_dispatch',created_at:'2026-09-16T17:35:00Z'
  }]}) : original(url,options);
  const out=await tick(env,{now,fetchImpl:f.fetch});
  assert.equal(out.state,'stalled');
});

test('prior-day early runner does not receive a new research grace period each morning', async () => {
  const f=fake(); const original=f.fetch;
  f.fetch=async(url,options)=>String(url).includes('/runs?') ? Response.json({workflow_runs:[{
    head_branch:'main',display_title:'Daily HK China memo — early runner',
    status:'in_progress',event:'schedule',created_at:'2026-09-15T17:35:00Z'
  }]}) : original(url,options);
  const out=await tick(env,{now,fetchImpl:f.fetch});
  assert.equal(out.state,'stalled');
  assert.equal(out.requiresAttention,true);
  assert.equal(f.calls.filter(x=>x.method==='POST').length,0);
});
