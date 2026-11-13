/** Execute the exact shipped migration and every RPC against real PostgreSQL/pgvector (PGlite).
 * No source rewriting, SQL repair, mock database, network or live credentials.
 * This does not establish hosted Supabase/Edge or concurrent worker correctness.
 */
import {PGlite} from '@electric-sql/pglite';
import {vector} from '@electric-sql/pglite-pgvector';
import {pgcrypto} from '@electric-sql/pglite/contrib/pgcrypto';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
const db=new PGlite({extensions:{vector,pgcrypto}});
let assertions=0;
function equal(actual,expected){assert.deepEqual(actual,expected);assertions++;}
async function rejected(fn,code){await assert.rejects(fn,error=>!code||error.code===code);assertions++;}
const migration=readFileSync(new URL('../backend/001_private.sql',import.meta.url),'utf8');
try {
 await db.exec('CREATE SCHEMA extensions; CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;');
 await db.exec(migration);
 console.log('Exact source migration executed successfully.');
 // Verify both action bodies take the shared canonical event lock before reviewer
 // serialization and before checking either event table. Lock presence is tested
 // below through pg_locks; this is not a multiworker race simulation.
 for(const action of ['feedback','selection']) {
   const branch=migration.split(`ELSIF action='${action}' AND principal.role='reviewer' THEN`)[1].split('ELSIF action=')[0];
   const guard="pg_advisory_xact_lock(1,hashtext((args->>'client_event_id')::uuid::text))";
   assert.ok(branch.indexOf(guard)>=0 && branch.indexOf(guard)<branch.indexOf('pg_advisory_xact_lock(hashtextextended(principal.reviewer,0))'));assertions++;
   assert.ok(branch.indexOf(guard)<branch.indexOf("WHERE event_id=(args->>'client_event_id')::uuid"));assertions++;
 }
 async function eventLockHeld(eventId) {
   const row=(await db.query("SELECT count(*)::int n FROM pg_locks WHERE locktype='advisory' AND classid=1 AND objid=((hashtext($1::uuid::text)::bigint & 4294967295)::oid) AND objsubid=2 AND granted",[eventId])).rows[0];
   equal(row.n,1);
 }

 await db.exec(`insert into memo_v2.tokens(hash,reviewer,role) values ('${'a'.repeat(64)}','alice','reviewer'),('${'b'.repeat(64)}','bob','reviewer'),('${'c'.repeat(64)}','ci','ci');`);
 const call=async(token,action,args={})=>(await db.query('select public.memo_v2_dispatch($1,$2,$3) result',[token.repeat(64),action,args])).rows[0].result;
 const ci=async(operation,args={})=>(await call('c','ci',{operation,arguments:args})).result;
 const item={id:'story',body:'Same fact.',canonical_body:'Same fact.',content_hash:'hash',edition_date:'2026-09-30',topics:['earnings'],tickers:['700 HK']};
 const edition={id:'edition',edition_date:'2026-09-30',items:[item]};
 equal(await ci('register_edition',{edition}),null);
 equal(await ci('latest_edition'),edition);
 equal(await ci('get_item',{item_id:'story'}),item);
 const feedback={item_id:'story',edition_id:'edition',label:'used',client_event_id:'11111111-1111-4111-8111-111111111111'};
 equal(await call('a','feedback',feedback),{saved:true,label:'used',client_event_id:feedback.client_event_id});
 equal(await call('a','feedback',feedback),{saved:true,label:'used',client_event_id:feedback.client_event_id});
 equal((await db.query('select count(*)::int n from memo_v2.events')).rows[0].n,1);
 await db.exec('BEGIN');await call('a','feedback',feedback);await eventLockHeld(feedback.client_event_id);await db.exec('ROLLBACK');
 for(const field of ['item_id','edition_id','label','client_event_id']) {
   const missing={...feedback};delete missing[field];await rejected(()=>call('a','feedback',missing));
   await rejected(()=>call('a','feedback',{...feedback,[field]:null}));
 }
 equal((await call('a','edition')).labels,{story:'used'});
 equal((await call('b','edition')).labels,{story:'unlabeled'});
 await rejected(()=>call('c','edition'),'42501');
 await rejected(()=>call('d','edition'),'28000');
 await rejected(()=>call('a','ci',{operation:'get_item',arguments:{item_id:'story'}}),'42501');
 await rejected(()=>ci('arbitrary_sql',{sql:'select 1'}));
 await rejected(()=>call('a','feedback',{...feedback,edition_id:'nope',client_event_id:'22222222-1111-4111-8111-111111111111'}),'23503');
 await rejected(()=>call('a','feedback',{...feedback,label:'cleared'}));
 await rejected(()=>call('b','feedback',feedback));
 equal(await ci('get_item_feedback',{item_ids:['story','unknown']}),{story:'used',unknown:'unlabeled'});
 equal(await ci('get_item_feedback',{item_ids:['story'],reviewer:'bob'}),{story:'unlabeled'});
 equal(await ci('get_item_feedback',{item_ids:['story'],reviewer:'alice'}),{story:'used'});
 await ci('save_preference_profile',{profile:{version:'one'}});
 equal(await ci('get_preference_profile',{version:'latest'}),{version:'one',approved_for_experiment:false});
 equal(await ci('get_preference_profile',{version:'one'}),{version:'one',approved_for_experiment:false});
 equal(await ci('get_preference_profile',{version:'missing'}),{});
 await ci('save_shadow_run',{run:{id:'r1',status:'rejected'}});
 equal((await db.query("select payload from memo_v2.runs where id='r1'")).rows[0].payload,{id:'r1',status:'rejected'});
 // Normalized-equivalent revisions share identity while preserving exact new presentation.
 const revised={...edition,id:'edition2',items:[{...item,body:'Same  fact.'}]};
 await ci('register_edition',{edition:revised});
 equal(await ci('latest_edition'),revised);
 equal((await ci('get_item',{item_id:'story'})).body,'Same fact.');
 await rejected(()=>ci('register_edition',{edition:{...edition,items:[]}}));
 await rejected(()=>ci('register_edition',{edition:{...edition,id:'bad-revision',items:[{...item,canonical_body:'Different fact.',body:'Different fact.'}]}}));
 equal(await ci('latest_edition'),revised); // Failed transaction did not register an edition.
 const query={vector:Array(1536).fill(1),model:'text-embedding-3-small',version:'1'};
 equal(await ci('has_embedding',{item_id:'story',model:query.model,version:query.version}),false);
 await ci('add_embedding',{...query,item_id:'story'});
 equal(await ci('has_embedding',{item_id:'story',model:query.model,version:query.version}),true);
 for(const overrides of [{item_id:'missing'},{model:'other'},{version:'2'}]) equal(await ci('has_embedding',{item_id:'story',model:query.model,version:query.version,...overrides}),false);
 await rejected(()=>call('a','ci',{operation:'has_embedding',arguments:{item_id:'story',model:query.model,version:query.version}}),'42501');
 let rows=await ci('search_history',{...query,topics:['earnings'],tickers:['700 HK'],date_from:'2026-01-01',date_to:'2026-10-01'});
 equal(rows.length,1);equal(rows[0].id,'story');equal(rows[0].label,'used');equal(rows[0].history_only,true);
 assert.ok(Number.isFinite(rows[0].similarity)&&Number.isFinite(rows[0].retrieval_score));assertions++;
 for(const overrides of [{model:'other'},{version:'2'},{date_from:'2026-10-01'},{tickers:['bad']},{topics:['bad']}]) equal(await ci('search_history',{...query,...overrides}),[]);
 await rejected(()=>ci('search_history',{...query,date_from:'garbage'}));
 await rejected(()=>ci('search_history',{...query,date_from:'2026-10-01',date_to:'2026-09-01'}));
 for(const bad of [[],[1],Array(1536).fill(0),Array(1536).fill('NaN'),Array(1536).fill('Infinity'),Array(1536).fill(null),Array(1536).fill(1e30),Array(1536).fill(1e-30)]) {
   await rejected(()=>ci('search_history',{...query,vector:bad}));
   await rejected(()=>ci('add_embedding',{...query,item_id:'story',vector:bad}));
 }
 for(const magnitude of [1e17,1e18,1e19,1e20,1e-20,1e-21]) {
   const boundary=Array(1536).fill(magnitude);
   const distance=(await db.query('select memo_v2.checked_vector($1) OPERATOR(extensions.<=>) memo_v2.checked_vector($1) distance',[boundary])).rows[0].distance;
   assert.ok(Number.isFinite(distance)&&Math.abs(distance)<1e-5);assertions++;
   await ci('add_embedding',{...query,item_id:'story',vector:boundary});
   const result=await ci('search_history',{...query,vector:boundary});
   equal(result.length,1);
   assert.ok(Number.isFinite(result[0].similarity)&&Number.isFinite(result[0].retrieval_score));assertions++;
 }
 await db.exec("update memo_v2.embeddings set body_hash='stale'");
 equal(await ci('has_embedding',{item_id:'story',model:query.model,version:query.version}),false);
 equal(await ci('search_history',query),[]);
 await ci('add_embedding',{...query,item_id:'story'});
 await call('a','feedback',{...feedback,label:'cleared',client_event_id:'33333333-1111-4111-8111-111111111111'});
 equal((await call('a','edition')).labels,{story:'unlabeled'});
 for(let n=0;n<58;n++) await call('a','feedback',{...feedback,client_event_id:String(n).padStart(8,'0')+'-aaaa-4111-8111-111111111111'});
 await rejected(()=>call('a','feedback',{...feedback,client_event_id:'44444444-1111-4111-8111-111111111111'}));
 equal((await call('a','feedback',feedback)).saved,true);
 await db.exec("update memo_v2.tokens set revoked=true where reviewer='alice'");
 await rejected(()=>call('a','edition'),'28000');
 // Selection snapshots are private weak positives, separate from explicit labels.
 const selectionEdition={id:'selection-edition',edition_date:'2026-10-01',items:[{...item,id:'pick-a'},{...item,id:'pick-b'}]};
 await ci('register_edition',{edition:selectionEdition});
 const snapshot={edition_id:selectionEdition.id,selected_item_ids:['pick-b','pick-a'],client_event_id:randomUUID()};
 equal(await call('b','selection',snapshot),{saved:true,client_event_id:snapshot.client_event_id,selected_item_ids:['pick-b','pick-a']});
 equal((await call('b','selection',snapshot)).saved,true);
 equal((await db.query('select count(*)::int n from memo_v2.selections')).rows[0].n,1);
 equal((await call('b','edition')).selected_item_ids,['pick-b','pick-a']);
 let signals=await ci('get_selection_signals',{item_ids:['pick-a','pick-b','unknown']});
 equal(signals['pick-a'],{selected:true,position:1,selection_count:1});
 equal(signals['pick-b'],{selected:true,position:0,selection_count:1});
 equal(signals.unknown,{selected:false,position:null,selection_count:0});
 equal((await ci('get_selection_signals',{item_ids:['pick-a'],reviewer:'alice'}))['pick-a'].selected,false);
 equal((await ci('get_item_feedback',{item_ids:['pick-a']}))['pick-a'],'unlabeled');
 await db.exec('BEGIN');await call('b','selection',snapshot);await eventLockHeld(snapshot.client_event_id);await db.exec('ROLLBACK');
 await rejected(()=>call('c','selection',snapshot),'42501');
 await rejected(()=>call('b','ci',{operation:'get_selection_signals',arguments:{item_ids:['pick-a']}}),'42501');
 for(const ids of [null,'bad',['pick-a','pick-a'],['missing'],[null],[''],Array.from({length:101},(_,n)=>String(n))]) await rejected(()=>call('b','selection',{...snapshot,client_event_id:randomUUID(),selected_item_ids:ids}));
 await rejected(()=>call('b','selection',{...snapshot,edition_id:'missing',selected_item_ids:[],client_event_id:randomUUID()}));
 await rejected(()=>call('b','selection',{...snapshot,client_event_id:'bad-uuid'}));
 for(const field of ['selected_item_ids','edition_id','client_event_id']) {const missing={...snapshot};delete missing[field];await rejected(()=>call('b','selection',missing));}
 await rejected(()=>call('b','selection',{...snapshot,selected_item_ids:['pick-a','pick-b']}));
 await rejected(()=>call('b','feedback',{item_id:'pick-a',edition_id:selectionEdition.id,label:'used',client_event_id:snapshot.client_event_id}));
 await rejected(()=>call('b','selection',{...snapshot,client_event_id:feedback.client_event_id}));
 await call('b','selection',{...snapshot,selected_item_ids:['pick-a'],client_event_id:randomUUID()});
 signals=await ci('get_selection_signals',{item_ids:['pick-a','pick-b']});
 equal(signals['pick-a'],{selected:true,position:0,selection_count:1});equal(signals['pick-b'].selected,false);
 await db.exec(`insert into memo_v2.tokens(hash,reviewer,role) values ('${'e'.repeat(64)}','charlie','reviewer')`);
 equal((await call('e','edition')).selected_item_ids,[]);
 await rejected(()=>call('e','selection',snapshot));
 await call('e','selection',{...snapshot,selected_item_ids:['pick-a'],client_event_id:randomUUID()});
 equal((await ci('get_selection_signals',{item_ids:['pick-a']}))['pick-a'].selection_count,2);
 await call('b','selection',{...snapshot,selected_item_ids:[],client_event_id:randomUUID()});
 equal((await call('b','edition')).selected_item_ids,[]);
 equal((await ci('get_selection_signals',{item_ids:['pick-a'],reviewer:'bob'}))['pick-a'].selected,false);
 equal((await ci('get_selection_signals',{item_ids:['pick-a']}))['pick-a'].selection_count,1);
 // Bob has three snapshots; feedback shares the same sixty-event limit.
 for(let n=0;n<57;n++) await call('b','feedback',{item_id:'pick-a',edition_id:selectionEdition.id,label:'used',client_event_id:randomUUID()});
 await rejected(()=>call('b','selection',{...snapshot,client_event_id:randomUUID()}));
 await rejected(()=>call('b','feedback',{item_id:'pick-a',edition_id:selectionEdition.id,label:'used',client_event_id:randomUUID()}));
 equal((await call('b','selection',snapshot)).saved,true);
 await call('e','selection',{edition_id:'edition',selected_item_ids:['story'],client_event_id:randomUUID()});
 signals=await ci('get_selection_signals',{item_ids:['story','pick-a'],reviewer:'charlie'});
 equal(signals.story.selected,true);equal(signals['pick-a'].selected,true);
 await call('e','selection',{edition_id:'edition',selected_item_ids:[],client_event_id:randomUUID()});
 signals=await ci('get_selection_signals',{item_ids:['story','pick-a'],reviewer:'charlie'});
 equal(signals.story.selected,false);equal(signals['pick-a'].selected,true);
 for(const role of ['anon','authenticated']) {
   await db.exec('SET ROLE '+role);
   await rejected(()=>db.query('select * from memo_v2.events'),'42501');
   await rejected(()=>db.query('select * from memo_v2.selections'),'42501');
   await rejected(()=>call('b','edition'),'42501');
   await db.exec('RESET ROLE');
 }
 await db.exec('SET ROLE service_role');equal((await call('b','edition')).edition.id,'selection-edition');await db.exec('RESET ROLE');
 // Newer same-day revision clears supersede old revision signals, not prior dates.
 await call('e','selection',{edition_id:'edition',selected_item_ids:['story'],client_event_id:randomUUID()});
 const selectionRevision={...selectionEdition,id:'selection-revision',items:[...selectionEdition.items,{...item,id:'pick-c'}]};
 await ci('register_edition',{edition:selectionRevision});
 await call('e','selection',{edition_id:selectionRevision.id,selected_item_ids:[],client_event_id:randomUUID()});
 signals=await ci('get_selection_signals',{item_ids:['pick-a','story'],reviewer:'charlie'});
 equal(signals['pick-a'],{selected:false,position:null,selection_count:0});equal(signals.story.selected,true);
 // The candidate SELECT is extracted from shipped SQL, so EXPLAIN verifies that
 // exact implementation rather than a hand-written approximation of the query.
 await db.query("INSERT INTO memo_v2.items SELECT 'bulk-'||n, $1::jsonb||jsonb_build_object('id','bulk-'||n) FROM generate_series(1,600) n",[item]);
 await db.query("INSERT INTO memo_v2.embeddings SELECT 'bulk-'||n,'text-embedding-3-small','1','hash',$2::jsonb,$1::extensions.vector FROM generate_series(1,600) n",[JSON.stringify(query.vector),item]);
 await db.exec('ANALYZE memo_v2.items; ANALYZE memo_v2.embeddings; SET enable_seqscan=off; SET enable_sort=off;');
 const candidateSource=migration.split('WITH candidates AS MATERIALIZED (')[1].split('), scored AS (')[0].trim();
 assert.ok(candidateSource.endsWith('LIMIT 200'));assertions++;
 const candidateQuery=candidateSource.replaceAll('query_vector','$1::extensions.vector').replace(/\ba->/g,'$2::jsonb->');
 const plan=JSON.stringify((await db.query('EXPLAIN (FORMAT JSON) '+candidateQuery,[JSON.stringify(query.vector),{model:query.model,version:query.version,topics:['earnings'],tickers:['700 HK']}])).rows);
 assert.match(plan,/embeddings_hnsw/);assertions++;
 equal((await ci('search_history',{...query,limit:500})).length,50);
 equal((await db.query("select current_setting('hnsw.max_scan_tuples',true) cap")).rows[0].cap,'20000'); // SET LOCAL is reset after RPC transaction.
 console.log(`PASS: ${assertions} assertions against actual PostgreSQL/pgvector; exact candidate query uses embeddings_hnsw. Hosted deployment/concurrency remain untested.`);
} finally {await db.close();}
