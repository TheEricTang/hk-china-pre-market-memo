import {richText,copyItems,reorder,FeedbackQueue,parsePublicMemo,SavedLabels,SelectionQueue,copyWithFeedback,restoreSelection} from './core.mjs';
const $=id=>document.getElementById(id);
let config,edition,items=[],labels=new SavedLabels(),selected=new Set(),pending={},queue,selectionQueue,selectionTimer,token='',newEdition=false,loadedHash=null;
const fragment=new URLSearchParams(location.hash.slice(1));token=fragment.get('review')||'';
const feedbackEnabled=()=>Boolean(token && config?.apiBase && queue);
function say(message){$('message').textContent=message;}
function endpoint(){const url=new URL(config.apiBase,location.href);if(url.protocol!=='https:' && !(url.origin===location.origin && ['127.0.0.1','localhost'].includes(url.hostname)))throw new Error('Feedback requires a secure endpoint.');return url;}
async function api(event){const url=endpoint();if(!event)url.searchParams.set('action','edition');const response=await fetch(url,{method:event?'POST':'GET',headers:{'Authorization':`Bearer ${token}`,...(event?{'Content-Type':'application/json'}:{})},body:event?JSON.stringify({action:'feedback',...event}):undefined,credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error(response.status===401?'Reviewer access expired or was revoked. Use a current private link.':'Feedback service is unavailable. Your unsaved feedback is kept on this device.');return response.json();}
function status(){const count=selected.size;$('selection-count').textContent=`${count} selected`;$('copy-selected').disabled=!count;const n=(queue?.events.length||0)+(selectionQueue?.events.length||0);$('sync-state').textContent=feedbackEnabled()?(n?`${n} feedback change${n===1?'':'s'} unsaved on this device.`:'All feedback changes saved.'):'Feedback is not connected. Copying does not record use.';$('retry-sync').hidden=!n;}
function render(){const list=$('stories');list.replaceChildren();items.forEach((item,index)=>{const li=document.createElement('li');li.className='story';const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(item.id);check.setAttribute('aria-label',`Select story ${index+1}`);check.addEventListener('change',()=>{if(check.checked)selected.add(item.id);else selected.delete(item.id);status();selectionChanged();});li.append(check);const content=document.createElement('div'),paragraph=document.createElement('p');paragraph.innerHTML=richText(item.body);content.append(paragraph);const actions=document.createElement('div');actions.className='story-tools';const button=(text,handler,disabled=false)=>{const b=document.createElement('button');b.textContent=text;b.disabled=disabled;b.onclick=handler;actions.append(b);};button('Copy',()=>copyStories([item]));button('↑ Move up',()=>{items=reorder(items,item.id,-1);render();selectionChanged();},index===0);button('↓ Move down',()=>{items=reorder(items,item.id,1);render();selectionChanged();},index===items.length-1);
if(feedbackEnabled()){button('Not relevant',()=>label(item,'not_relevant').catch(e=>say(e.message)));button('Undo label',()=>label(item,'cleared').catch(e=>say(e.message)));const state=document.createElement('span');state.className='story-state';state.textContent=pending[item.id]?`Unsaved: ${pending[item.id]}`:(labels.current?`Saved: ${labels.values[item.id]||'unlabeled'}`:'Saved label not refreshed');actions.append(state);}content.append(actions);li.append(content);list.append(li);});status();}
function selectionChanged(){
  if(!feedbackEnabled() || !selectionQueue)return;
  try {
    selectionQueue.add({action:'selection',edition_id:edition.id,selected_item_ids:items.filter(i=>selected.has(i.id)).map(i=>i.id),client_event_id:crypto.randomUUID()});
    status();clearTimeout(selectionTimer);selectionTimer=setTimeout(sync,400);
  } catch(error){say(error.message);}
}
async function copyStories(chosen){
  const copiedEdition=edition.id;
  try {
    const result=await copyWithFeedback(chosen,copyItems,feedbackEnabled()?copied=>{
      for(const item of copied){queue.add({item_id:item.id,edition_id:copiedEdition,label:'used',client_event_id:crypto.randomUUID()});pending[item.id]='used';}
    }:null);
    render();
    if(result.feedbackError){say('Copied with source links, but feedback could not be fully saved: '+result.feedbackError);return;}
    if(result.queued){await sync();say(queue.events.length?'Copied. Use feedback is waiting to sync.':'Copied with source links and recorded as useful.');}
    else say('Copied with source links. Feedback is not connected, so this copy was not recorded.');
  }catch(_){say('Copy failed. Nothing was marked useful. Allow clipboard access and retry.');}
}
async function label(item,value){const event={item_id:item.id,edition_id:edition.id,label:value,client_event_id:crypto.randomUUID()};queue.add(event);pending[item.id]=value;render();await sync();}
async function sync(){if(!queue)return;try{await queue.flush(api,event=>{labels.invalidate();delete pending[event.item_id];for(const e of queue.events)pending[e.item_id]=e.label;});if(selectionQueue)await selectionQueue.flush(api);await labels.refresh(()=>api(),edition.id);}catch(error){say(error.message);}finally{render();}}
async function publicStatus(){const response=await fetch(config.publicStatus,{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(10000)});if(!response.ok)throw new Error('The published edition could not be loaded.');const receipt=await response.json();if(!/^\d{4}-\d{2}-\d{2}$/.test(receipt.editionDate)||!/^[a-f0-9]{64}$/.test(receipt.memoSha256))throw new Error('Invalid publication receipt.');return receipt;}
function freshness(){const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());$('freshness').textContent=edition.edition_date===today?'Today’s published edition. Independent factual review is not certified here.':`Showing the ${edition.edition_date} edition. Check the live page for the trading-day publication status.`;}
async function load(){say('');let receipt,restoredSelection=[];try{receipt=await publicStatus();}catch(error){say(error.message);}if(token && config.apiBase){const payload=await api();if(!payload.edition?.items?.length)throw new Error('No edition has been registered for review yet. The existing daily memo is unaffected.');edition=payload.edition;restoredSelection=payload.selected_item_ids||[];labels.set(payload.labels||{});const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token));const key='hk-memo-v2-feedback-'+Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');queue=new FeedbackQueue(localStorage,key);selectionQueue=new SelectionQueue(localStorage,key+'-selections');pending={};for(const e of queue.events)pending[e.item_id]=e.label;$('access').textContent='Private reviewer mode · successful copies count as useful; selections and order are saved as possible interest. Undo a label at any time.';}else{if(!receipt)throw new Error('Published edition unavailable; please use the existing daily memo.');const r=await fetch(new URL(`memo-${receipt.editionDate}.md`,config.publicMemoBase),{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(15000)});if(!r.ok)throw new Error('The memo text could not be loaded.');const markdown=await r.text(),digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(markdown)),hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');if(hash!==receipt.memoSha256)throw new Error('The edition is updating. Reload once publication finishes.');edition=parsePublicMemo(markdown,receipt.editionDate);$('access').textContent=token?'Feedback is not configured yet. You can still select and copy the published news.':'Read-only workspace · a private reviewer link enables feedback.';}
loadedHash=feedbackEnabled()?(edition.source_version?.startsWith('sha256:')?edition.source_version.slice(7):null):receipt?.memoSha256;const restored=restoreSelection(edition.items,edition.id,restoredSelection,selectionQueue?.events||[]);items=restored.items;selected=new Set(restored.selectedIds);$('edition').textContent=`Published edition · ${edition.edition_date}`;freshness();newEdition=Boolean(receipt && (receipt.editionDate>edition.edition_date || (receipt.editionDate===edition.edition_date && loadedHash && receipt.memoSha256!==loadedHash)));$('new-edition').hidden=!newEdition;render();if(queue)await sync();}
$('select-all').onclick=()=>{selected=new Set(items.map(i=>i.id));render();selectionChanged();};$('clear-selection').onclick=()=>{selected.clear();render();selectionChanged();};$('copy-selected').onclick=()=>copyStories(items.filter(i=>selected.has(i.id)));$('retry-sync').onclick=sync;$('load-latest').onclick=()=>load().catch(e=>say(e.message));
window.addEventListener('online',sync);
window.addEventListener('storage', async event => {
  if (!queue || (event.key !== null && event.key !== queue.key && !event.key.startsWith(queue.prefix) && event.key !== selectionQueue?.key && !event.key.startsWith(selectionQueue?.prefix||'__none__'))) return;
  try {
    labels.invalidate();
    queue.refresh();
    selectionQueue?.refresh();
    pending = {};
    for (const change of queue.events) pending[change.item_id] = change.label;
    render();
    // Refresh saved labels without changing story order or the current selection.
    await labels.refresh(() => api(), edition.id);
    queue.refresh();
    selectionQueue?.refresh();
    pending = {};
    for (const change of queue.events) pending[change.item_id] = change.label;
    render();
  } catch (error) { say(error.message); }
});
try{const response=await fetch('./config.json',{cache:'no-store'});if(!response.ok)throw new Error('Workspace configuration unavailable.');config=await response.json();await load();setInterval(async()=>{if(document.visibilityState!=='visible'||!edition)return;freshness();try{const receipt=await publicStatus();if((receipt.editionDate>edition.edition_date || (receipt.editionDate===edition.edition_date && loadedHash && receipt.memoSha256!==loadedHash))){newEdition=true;$('new-edition').hidden=false;}}catch(_){}},60000);}catch(error){$('edition').textContent='Workspace unavailable';say(error.message);$('access').textContent='The existing daily memo remains available at the link above.';}
