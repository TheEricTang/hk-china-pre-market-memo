// Deploy as memo-v2 in the dedicated project with --no-verify-jwt: scoped opaque tokens are checked by the RPC.
const url = Deno.env.get('SUPABASE_URL')!;
const service = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const origin = Deno.env.get('V2_ALLOWED_ORIGIN')!;
const ciOperations = new Set(['register_edition','latest_edition','get_item','get_item_feedback','get_preference_profile','save_preference_profile','save_shadow_run','add_embedding','has_embedding','search_history']);
Deno.serve(async (request: Request) => {
  const headers: Record<string,string> = {'Content-Type':'application/json','Cache-Control':'no-store','Vary':'Origin'};
  const requestOrigin=request.headers.get('origin');
  const respond=(body: unknown,status=200)=>new Response(JSON.stringify(body),{status,headers});
  if (!origin || !url || !service) return respond({error:'unavailable'},503);
  if (requestOrigin && requestOrigin!==origin) return respond({error:'forbidden'},403);
  if (requestOrigin===origin) {
    headers['Access-Control-Allow-Origin']=origin;
    headers['Access-Control-Allow-Headers']='Authorization, Content-Type';
    headers['Access-Control-Allow-Methods']='GET, POST, OPTIONS';
  }
  if(request.method==='OPTIONS') return new Response(null,{status:204,headers});
  const match=/^Bearer ([A-Za-z0-9_-]{40,200})$/.exec(request.headers.get('authorization')||'');
  if(!match) return respond({error:'unauthorized'},401);
  if(!['GET','POST'].includes(request.method)) return respond({error:'method not allowed'},405);
  try {
    let body: Record<string,any>;
    if(request.method==='GET') body={action:new URL(request.url).searchParams.get('action')};
    else {
      if(!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) return respond({error:'JSON required'},415);
      const reader=request.body?.getReader(); const chunks: Uint8Array[]=[]; let size=0;
      if(!reader) return respond({error:'invalid request'},400);
      while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>2000000){await reader.cancel();return respond({error:'too large'},413);}chunks.push(value);}
      const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.length;}
      body=JSON.parse(new TextDecoder().decode(bytes));
    }
    if (!body || typeof body!=='object') return respond({error:'invalid request'},400);
    if(request.method==='GET' && body.action!=='edition') return respond({error:'invalid request'},400);
    if(request.method==='POST' && !['feedback','ci'].includes(body.action)) return respond({error:'invalid request'},400);
    if(body.action==='ci' && (!ciOperations.has(body.operation) || requestOrigin)) return respond({error:'forbidden'},403);
    const tokenHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(match[1])))).map(x=>x.toString(16).padStart(2,'0')).join('');
    const response=await fetch(`${url}/rest/v1/rpc/memo_v2_dispatch`,{method:'POST',headers:{'Content-Type':'application/json',apikey:service,Authorization:`Bearer ${service}`},body:JSON.stringify({token_hash:tokenHash,action:body.action,args:body}),signal:AbortSignal.timeout(15000)});
    if(!response.ok){const error=await response.json();return respond({error:error.code==='28000'?'unauthorized':error.code==='42501'?'forbidden':'request rejected'},error.code==='28000'?401:error.code==='42501'?403:400);}
    return respond(await response.json());
  }catch{return respond({error:'request failed'},400);}
});
