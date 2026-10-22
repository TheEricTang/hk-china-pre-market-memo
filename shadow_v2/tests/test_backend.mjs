// Execute actual Edge handler in Node with only Deno environment and fetch mocked.
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
let handler, calls=[];
const settings={SUPABASE_URL:'https://dedicated.supabase.co',SUPABASE_SERVICE_ROLE_KEY:'private-service-key',V2_ALLOWED_ORIGIN:'https://review.example'};
const context=vm.createContext({Request,Response,URL,TextEncoder,TextDecoder,Uint8Array,AbortSignal,crypto:webcrypto,Deno:{env:{get:name=>settings[name]},serve:fn=>{handler=fn}},fetch:async(url,opts)=>{
  const body=JSON.parse(opts.body); calls.push({url,body});
  if(body.token_hash!==await hash('a'.repeat(43))) return Response.json({code:'28000'},{status:400});
  return Response.json(body.action==='edition'?{edition:{id:'test'},labels:{}}:{result:null});
}});
async function hash(s){return Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(s))).toString('hex')}
vm.runInContext(stripTypeScriptTypes(readFileSync(new URL('../backend/index.ts',import.meta.url),'utf8')),context);
let response=await handler(new Request('https://api.example/?action=edition'));
assert.equal(response.status,401); assert.equal(calls.length,0);
response=await handler(new Request('https://api.example/?action=edition',{headers:{authorization:'Bearer '+ 'b'.repeat(43)}}));
assert.equal(response.status,401);
response=await handler(new Request('https://api.example/?action=edition',{headers:{authorization:'Bearer '+ 'a'.repeat(43),origin:'https://evil.example'}}));
assert.equal(response.status,403);
response=await handler(new Request('https://api.example/?action=edition',{headers:{authorization:'Bearer '+ 'a'.repeat(43),origin:settings.V2_ALLOWED_ORIGIN}}));
assert.equal(response.status,200); assert.equal(response.headers.get('access-control-allow-origin'),settings.V2_ALLOWED_ORIGIN);
assert.equal(response.headers.get('cache-control'),'no-store');
assert.equal(calls.at(-1).body.token_hash,await hash('a'.repeat(43)));
assert.ok(!JSON.stringify(calls).includes('a'.repeat(43)));
response=await handler(new Request('https://api.example/',{method:'POST',headers:{authorization:'Bearer '+ 'a'.repeat(43),'content-type':'text/plain'},body:'{}'}));
assert.equal(response.status,415);
response=await handler(new Request('https://api.example/',{method:'POST',headers:{authorization:'Bearer '+ 'a'.repeat(43),'content-type':'application/json',origin:settings.V2_ALLOWED_ORIGIN},body:JSON.stringify({action:'ci',operation:'latest_edition'})}));
assert.equal(response.status,403);
response=await handler(new Request('https://api.example/',{method:'POST',headers:{authorization:'Bearer '+ 'a'.repeat(43),'content-type':'application/json'},body:JSON.stringify({action:'ci',operation:'delete_everything'})}));
assert.equal(response.status,403);
response=await handler(new Request('https://api.example/',{method:'POST',headers:{authorization:'Bearer '+ 'a'.repeat(43),'content-type':'application/json'},body:JSON.stringify({action:'ci',operation:'has_embedding',arguments:{item_id:'story',model:'text-embedding-3-small',version:'1'}})}));
assert.equal(response.status,200);assert.equal(calls.at(-1).body.args.operation,'has_embedding');
response=await handler(new Request('https://api.example/',{method:'POST',headers:{authorization:'Bearer '+ 'a'.repeat(43),'content-type':'application/json',origin:settings.V2_ALLOWED_ORIGIN},body:JSON.stringify({action:'selection',edition_id:'edition',selected_item_ids:['story'],client_event_id:'11111111-1111-4111-8111-111111111111'})}));
assert.equal(response.status,200);assert.equal(calls.at(-1).body.action,'selection');assert.deepEqual(Array.from(calls.at(-1).body.args.selected_item_ids),['story']);
response=await handler(new Request('https://api.example/',{method:'POST',headers:{authorization:'Bearer '+ 'a'.repeat(43),'content-type':'application/json'},body:JSON.stringify({action:'ci',operation:'get_selection_signals',arguments:{item_ids:['story']}})}));
assert.equal(response.status,200);assert.equal(calls.at(-1).body.args.operation,'get_selection_signals');
console.log('Edge transport checks passed (mock RPC; live SQL not exercised).');
