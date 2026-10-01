// Pure functions shared by the browser and offline regression tests.
export const LINK = /\[\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)\]|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
export function plainText(body) {
  return body.replace(LINK, (_, a, b, c, d) => `${a || c} (${b || d})`).replace(/\*\*([^*]+)\*\*/g, '$1');
}
export function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
export function richText(body) {
  let html = '', start = 0;
  for (const match of body.matchAll(LINK)) {
    html += escapeHtml(body.slice(start, match.index));
    const url = match[2] || match[4], label = match[1] || match[3];
    html += `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">[${escapeHtml(label)}]</a>`;
    start = match.index + match[0].length;
  }
  html += escapeHtml(body.slice(start));
  return html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
export function clipboardPayload(items) {
  return {plain:items.map(i => plainText(i.body)).join('\n\n'),html:items.map(i => `<p>${richText(i.body)}</p>`).join('\n')};
}
export async function copyItems(items, clipboard = globalThis.navigator?.clipboard, Clipboard = globalThis.ClipboardItem) {
  if (!items.length) throw new Error('Select a story first.');
  const data = clipboardPayload(items);
  if (clipboard?.write && Clipboard) {
    await clipboard.write([new Clipboard({'text/plain':new Blob([data.plain],{type:'text/plain'}),'text/html':new Blob([data.html],{type:'text/html'})})]);
  } else if (clipboard?.writeText) { await clipboard.writeText(data.plain); }
  else throw new Error('Clipboard access is unavailable.');
}
export function reorder(items, id, direction) {
  const next = [...items], index = next.findIndex(i => i.id === id), target = index + direction;
  if (index < 0 || target < 0 || target >= items.length || ![-1,1].includes(direction)) return next;
  [next[index],next[target]]=[next[target],next[index]]; return next;
}
export class FeedbackQueue {
  constructor(storage, key) {
    this.storage = storage;
    this.key = key;
    this.prefix = `${key}:event:`;
    this.events = [];
    this.busy = false;
    this.clock = 0;
    this.refresh();
  }
  valid(event) {
    return event && ['used', 'not_relevant', 'cleared'].includes(event.label)
      && ['item_id', 'edition_id', 'client_event_id'].every(k => typeof event[k] === 'string');
  }
  eventKey(event) { return this.prefix + encodeURIComponent(event.client_event_id); }
  refresh() {
    // Legacy migration is restartable. Never erase its only copy before every write succeeds.
    const legacy = this.storage.getItem(this.key);
    if (legacy) {
      const old = JSON.parse(legacy);
      if (!Array.isArray(old)) throw new Error('Invalid saved feedback queue.');
      for (const [index, event] of old.entries()) {
        if (!this.valid(event)) throw new Error('Invalid saved feedback event.');
        const key = this.eventKey(event);
        if (!this.storage.getItem(key)) {
          this.storage.setItem(key, JSON.stringify({event, order: index}));
        }
      }
      this.storage.removeItem(this.key);
    }
    const entries = [];
    for (let index = 0; index < this.storage.length; index++) {
      const key = this.storage.key(index);
      if (!key?.startsWith(this.prefix)) continue;
      const record = JSON.parse(this.storage.getItem(key));
      if (!record || !this.valid(record.event) || !Number.isFinite(record.order)) {
        throw new Error('Invalid saved feedback event.');
      }
      entries.push(record);
    }
    entries.sort((a, b) => a.order - b.order || a.event.client_event_id.localeCompare(b.event.client_event_id));
    this.clock = Math.max(this.clock, ...entries.map(e => e.order));
    this.events = entries.map(e => e.event);
    return this.events;
  }
  add(event) {
    try {
      this.refresh();
      if (!this.valid(event)) throw new Error('Invalid feedback event.');
      const key = this.eventKey(event);
      const existing = this.storage.getItem(key);
      if (existing) {
        if (JSON.stringify(JSON.parse(existing).event) !== JSON.stringify(event)) {
          throw new Error('Feedback identity conflict.');
        }
        return;
      }
      this.clock = Math.max(Date.now(), this.clock + 1);
      this.storage.setItem(key, JSON.stringify({event, order: this.clock}));
      this.refresh();
    } catch (_) {
      throw new Error('Feedback could not be saved locally. Please try again.');
    }
  }
  async flush(send, onSaved = () => {}) {
    if (this.busy) return;
    this.busy = true;
    try {
      while (this.refresh().length) {
        const event = this.events[0];
        const response = await send(event);
        if (response.saved !== true || response.client_event_id !== event.client_event_id
            || response.label !== event.label) throw new Error('Feedback was not confirmed.');
        // Only this acknowledged UUID is removed. Another tab's additions remain intact.
        this.storage.removeItem(this.eventKey(event));
        this.refresh();
        onSaved(event);
      }
    } finally { this.busy = false; }
  }
}
export function parsePublicMemo(markdown,date) {
  const lines=markdown.split(/\r?\n/), items=lines.filter(l=>l.startsWith('- ')).map((l,i)=>({id:`public-${date}-${i}`,position:i+1,body:l.slice(2),edition_date:date}));
  return {id:`public-${date}`,edition_date:date,title:lines[0],research_cutoff:lines[1]||'',items};
}

// Server acknowledgements confirm an event, not the reviewer's current label.
export class SavedLabels {
  constructor() { this.values = {}; this.current = false; this.generation = 0; }
  set(values) { this.generation++; this.values = values; this.current = true; }
  invalidate() { this.generation++; this.current = false; }
  async refresh(load, editionId) {
    const generation = ++this.generation;
    this.current = false;
    const payload = await load();
    if (generation !== this.generation) return;
    if (payload.edition?.id !== editionId) return;
    this.values = payload.labels || {};
    this.current = true;
  }
}
