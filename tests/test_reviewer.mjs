import test from 'node:test';
import assert from 'node:assert/strict';
import {richText,clipboardPayload,copyItems,reorder,FeedbackQueue,SavedLabels} from '../docs/v2/core.mjs';
test('copied paragraphs retain sources and chosen order, exclude UI',()=>{const x=[{id:'a',body:'**Alpha:** New fact. [[News](https://example.com/a)]'},{id:'b',body:'Beta: Other fact.'}];const p=clipboardPayload(reorder(x,'b',-1));assert.ok(p.plain.startsWith('Beta:'));assert.match(p.plain,/News \(https:\/\/example.com\/a\)/);assert.ok(p.html.includes('<strong>Alpha:</strong>'));assert.ok(!p.html.includes('Copy &'));});
test('source and text cannot inject markup or javascript',()=>{const x=richText('<img onerror="bad"> [x](javascript:bad) [[safe](https://example.com/?a="b)]');assert.ok(!x.includes('<img'));assert.ok(!x.includes('href="javascript:'));assert.match(x,/&quot;/);});
test('copy failure rejects before any downstream use action',async()=>{let marked=false;await assert.rejects(async()=>{await copyItems([{body:'x'}],{writeText:async()=>{throw Error('denied');}},undefined);marked=true;});assert.equal(marked,false);});
test('plain clipboard fallback works and empty copy rejects',async()=>{let text;await copyItems([{body:'abc'}],{writeText:async x=>{text=x;}},undefined);assert.equal(text,'abc');await assert.rejects(copyItems([],{}));});
const storage=()=>{
  const data=new Map();
  return {
    get length(){return data.size;},
    key:index=>[...data.keys()][index]??null,
    getItem:key=>data.get(key)??null,
    setItem:(key,value)=>data.set(key,value),
    removeItem:key=>data.delete(key),
  };
};
test('offline queue persists retries unchanged and sends undo in order',async()=>{const s=storage(),q=new FeedbackQueue(s,'reviewerA'),a={item_id:'i',edition_id:'e',label:'used',client_event_id:'1'},b={...a,label:'cleared',client_event_id:'2'};q.add(a);q.add(b);await assert.rejects(q.flush(async()=>{throw Error('offline');}));const restored=new FeedbackQueue(s,'reviewerA'),sent=[];await restored.flush(async e=>{sent.push(e);return {saved:true,...e};});assert.deepEqual(sent,[a,b]);assert.equal(restored.events.length,0);assert.equal(new FeedbackQueue(s,'reviewerB').events.length,0);});
test('wrong server acknowledgement never appears saved',async()=>{const q=new FeedbackQueue(storage(),'a');q.add({item_id:'i',edition_id:'e',label:'used',client_event_id:'1'});await assert.rejects(q.flush(async()=>({saved:true,client_event_id:'other',label:'used'})));assert.equal(q.events.length,1);});
test('storage failure does not silently drop a label',()=>{const q=new FeedbackQueue({...storage(),setItem:()=>{throw Error('full');}},'a');assert.throws(()=>q.add({item_id:'i',edition_id:'e',label:'used',client_event_id:'1'}));assert.equal(q.events.length,0);});
test('storage failure after server acknowledgement keeps idempotent retry pending',async()=>{
  let fail=false;
  const s=storage(),remove=s.removeItem;
  s.removeItem=k=>{if(fail)throw Error('full');remove(k);};
  const q=new FeedbackQueue(s,'a');
  const event={item_id:'i',edition_id:'e',label:'used',client_event_id:'1'};
  q.add(event);fail=true;
  await assert.rejects(q.flush(async()=>({saved:true,...event})));
  assert.deepEqual(q.events,[event]);
  fail=false;
  const sent=[];
  await q.flush(async e=>{sent.push(e);return {saved:true,...e};});
  assert.deepEqual(sent,[event]);
});
test('invalid reorder cannot drop or duplicate stories',()=>{const items=[{id:'a'},{id:'b'}];assert.deepEqual(reorder(items,'missing',1),items);assert.deepEqual(reorder(items,'a',-1),items);assert.deepEqual(reorder(items,'a',2),items);});

const event=id=>({item_id:'i',edition_id:'e',label:'used',client_event_id:id});
test('two stale tabs append atomically and restart recovers both',()=>{
  const s=storage(),a=new FeedbackQueue(s,'hash-A'),b=new FeedbackQueue(s,'hash-A');
  a.add(event('a'));b.add(event('b'));
  assert.deepEqual(new FeedbackQueue(s,'hash-A').events.map(e=>e.client_event_id),['a','b']);
  assert.equal(new FeedbackQueue(s,'hash-B').events.length,0);
});
test('ack removal cannot overwrite another tab append and current storage is read before flush',async()=>{
  const s=storage(),a=new FeedbackQueue(s,'a'),b=new FeedbackQueue(s,'a');
  b.add(event('first'));
  const sent=[];
  await a.flush(async e=>{sent.push(e.client_event_id);if(sent.length===1)b.add(event('second'));return {saved:true,...e};});
  assert.deepEqual(sent,['first','second']);
  assert.equal(new FeedbackQueue(s,'a').events.length,0);
});
test('simultaneous acknowledgement of the same UUID is harmless',async()=>{
  const s=storage(),a=new FeedbackQueue(s,'a'),b=new FeedbackQueue(s,'a');
  a.add(event('same'));let release;
  const wait=new Promise(resolve=>{release=resolve;});
  const first=a.flush(async e=>{await wait;return {saved:true,...e};});
  await b.flush(async e=>({saved:true,...e}));release();await first;
  assert.equal(new FeedbackQueue(s,'a').events.length,0);
});
test('partial legacy migration retains original until all writes finish',()=>{
  const s=storage(),set=s.setItem;
  s.setItem('a',JSON.stringify([event('a'),event('b')]));let writes=0;
  s.setItem=(k,v)=>{if(++writes===2)throw Error('quota');set(k,v);};
  assert.throws(()=>new FeedbackQueue(s,'a'));
  assert.ok(s.getItem('a'));
  s.setItem=set;
  const q=new FeedbackQueue(s,'a');
  assert.equal(s.getItem('a'),null);
  assert.deepEqual(q.events,[event('a'),event('b')]);
});
test('clock rollback preserves each tabs action order',()=>{
  const s=storage(),q=new FeedbackQueue(s,'a'),now=Date.now;
  try {Date.now=()=>100;q.add(event('z'));Date.now=()=>1;q.add(event('a'));}
  finally {Date.now=now;}
  assert.deepEqual(new FeedbackQueue(s,'a').events.map(e=>e.client_event_id),['z','a']);
});

test('late duplicate used acknowledgement cannot overwrite a subsequently saved undo', async () => {
  const s=storage(),a=new FeedbackQueue(s,'reviewer'),b=new FeedbackQueue(s,'reviewer');
  const labels=new SavedLabels();labels.set({});
  const used=event('used'),undo={...event('undo'),label:'cleared'};
  a.add(used);let release;
  const delayed=new Promise(resolve=>{release=resolve;});
  let serverLabel='used';
  const read=async()=>({edition:{id:'e'},labels:{i:serverLabel==='cleared'?'unlabeled':serverLabel}});
  const slow=a.flush(async e=>{await delayed;return {saved:true,...e};},()=>labels.invalidate());
  await b.flush(async e=>({saved:true,...e}));
  b.add(undo);
  await b.flush(async e=>{serverLabel=e.label;return {saved:true,...e};});
  await labels.refresh(read,'e');
  release();await slow;
  assert.equal(labels.current,false);
  await labels.refresh(read,'e');
  assert.equal(labels.values.i,'unlabeled');
  assert.equal(labels.current,true);
});
test('stale label reads and unavailable or wrong-edition responses never claim a current saved label',async()=>{
  const labels=new SavedLabels();labels.set({i:'used'});let release;
  const old=labels.refresh(()=>new Promise(resolve=>{release=resolve;}),'e');
  await labels.refresh(async()=>({edition:{id:'e'},labels:{i:'unlabeled'}}),'e');
  release({edition:{id:'e'},labels:{i:'used'}});await old;
  assert.equal(labels.values.i,'unlabeled');
  await assert.rejects(labels.refresh(async()=>{throw Error('offline');},'e'));
  assert.equal(labels.current,false);
  await labels.refresh(async()=>({edition:{id:'next'},labels:{i:'used'}}),'e');
  assert.equal(labels.current,false);
});
