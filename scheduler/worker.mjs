import { holidays, calendarYears } from './calendar.mjs';
const SITE = 'https://theerictang.github.io/hk-china-pre-market-memo/';
const WORKFLOW = 'https://api.github.com/repos/TheEricTang/hk-china-pre-market-memo/actions/workflows/daily-memo.yml';
const START = 6 * 60 + 35;
const TARGET = 7 * 60 + 30;
const LAST_START = 7 * 60 + 30;
const END = 8 * 60;
const MAX_DAILY_DISPATCHES = 3;

function hkClock(now) {
  const hk = new Date(now.getTime() + 8 * 3600000);
  return { date: hk.toISOString().slice(0, 10), day: hk.getUTCDay(),
    minutes: hk.getUTCHours() * 60 + hk.getUTCMinutes() };
}
async function boundedText(response, limit = 1048576) {
  if (!response.ok) throw new Error(`Public page HTTP ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let size = 0, result = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return result + decoder.decode();
      size += value.byteLength;
      if (size > limit) throw new Error('Public page too large');
      result += decoder.decode(value, { stream: true });
    }
  } finally { await reader.cancel(); }
}
async function publicEditionIsReady(date, now, fetchImpl) {
  try {
    const query = `?check=${now.getTime()}`;
    const [statusResponse, pageResponse] = await Promise.all([
      fetchImpl(SITE + 'status.json' + query, { signal: AbortSignal.timeout(10000) }),
      fetchImpl(SITE + query, { signal: AbortSignal.timeout(10000) }),
    ]);
    const [statusText, html] = await Promise.all([boundedText(statusResponse, 16384), boundedText(pageResponse)]);
    const status = JSON.parse(statusText);
    const [year, month, day] = date.split('-');
    const mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(month)-1];
    const title = `Morning Market Memo | ${day} ${mon} ${year} | HK/China Pre-Open`;
    const h1 = /<h1\b[^>]*>([\s\S]*?)<\/h1>/i.exec(html)?.[1].replace(/<[^>]+>/g, '').trim();
    const hash = /<meta\s+name=["']memo-sha256["']\s+content=["']([a-f0-9]{64})["']/i.exec(html)?.[1];
    const cutoff = Date.parse(status.researchCutoff), finished = Date.parse(status.generatedAt);
    return status.editionDate === date && status.editionMode === 'preopen'
      && status.qualityPassed === true && /^[a-f0-9]{64}$/.test(status.memoSha256)
      && hash === status.memoSha256 && h1 === title
      && Number.isFinite(cutoff) && Number.isFinite(finished)
      && cutoff <= finished && finished <= now.getTime()
      && hkClock(new Date(cutoff)).date === date
      && hkClock(new Date(cutoff)).minutes >= START;
  } catch { return false; }
}

export async function tick(env, { now = new Date(), fetchImpl = fetch } = {}) {
  const clock = hkClock(now);
  if (env.ENABLED !== 'true' || holidays.has(clock.date) || clock.day === 0 || clock.day === 6 || clock.minutes < START || clock.minutes >= END) {
    return { state: 'skipped', date: clock.date };
  }
  if (!calendarYears.has(Number(clock.date.slice(0, 4)))) throw new Error('HK trading calendar needs renewal');
  if (await publicEditionIsReady(clock.date, now, fetchImpl)) return { state: 'delivered', date: clock.date };
  const deadlineMissed = clock.minutes >= TARGET;
  if (!env.GITHUB_TOKEN) throw new Error('Scheduler GitHub credential missing');
  const headers = { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'hk-memo-delivery-scheduler' };
  const result = await fetchImpl(WORKFLOW + '/runs?branch=main&per_page=30', { headers, signal: AbortSignal.timeout(10000) });
  if (!result.ok) throw new Error(`GitHub status HTTP ${result.status}`);
  const runs = (await result.json()).workflow_runs;
  if (!Array.isArray(runs)) throw new Error('GitHub status missing workflow runs');
  if (runs.some(run => run.head_branch === 'main' && run.status !== 'completed')) {
    return { state: 'running', date: clock.date, deadlineMissed };
  }
  const windowStart = Date.parse(clock.date + 'T06:35:00+08:00');
  const dispatched = runs.filter(run => run.event === 'workflow_dispatch' && run.head_branch === 'main'
    && Date.parse(run.created_at) >= windowStart).length;
  if (dispatched >= MAX_DAILY_DISPATCHES || clock.minutes > LAST_START) {
    return { state: 'recovery_exhausted', date: clock.date, deadlineMissed };
  }
  const response = await fetchImpl(WORKFLOW + '/dispatches', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(10000),
    body: JSON.stringify({ ref: 'main', inputs: { automatic: true, generate: true, edition_mode: 'preopen' } }),
  });
  if (!response.ok) throw new Error(`GitHub dispatch HTTP ${response.status}`);
  return { state: 'dispatched', date: clock.date, deadlineMissed };
}

export default {
  async scheduled(controller, env) {
    // Use actual execution time, never backdate a delayed trigger to its intended time.
    const result = await tick(env);
    console.log(JSON.stringify(result));
    if (result.deadlineMissed) throw new Error(`Memo delivery target missed for ${result.date}: ${result.state}`);
  },
  async fetch() { return new Response('Not found', { status: 404 }); },
};
