-- Apply ONLY in a dedicated v2 Supabase project. Never apply to the v1 project.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE SCHEMA IF NOT EXISTS memo_v2;
REVOKE ALL ON SCHEMA memo_v2 FROM PUBLIC, anon, authenticated;
CREATE TABLE memo_v2.editions(id text PRIMARY KEY, day date NOT NULL, payload jsonb NOT NULL, seq bigint GENERATED ALWAYS AS IDENTITY);
CREATE TABLE memo_v2.items(id text PRIMARY KEY, payload jsonb NOT NULL);
CREATE TABLE memo_v2.membership(edition_id text REFERENCES memo_v2.editions, item_id text REFERENCES memo_v2.items, PRIMARY KEY(edition_id,item_id));
CREATE TABLE memo_v2.tokens(hash text PRIMARY KEY, reviewer text NOT NULL, role text NOT NULL CHECK(role IN ('reviewer','ci')), revoked boolean NOT NULL DEFAULT false);
CREATE TABLE memo_v2.events(seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_id uuid UNIQUE NOT NULL, reviewer text NOT NULL, edition_id text NOT NULL, item_id text NOT NULL, label text NOT NULL CHECK(label IN ('used','not_relevant','cleared')), created timestamptz NOT NULL DEFAULT now(), FOREIGN KEY(edition_id,item_id) REFERENCES memo_v2.membership);
CREATE TABLE memo_v2.profiles(version text PRIMARY KEY, payload jsonb NOT NULL, seq bigint GENERATED ALWAYS AS IDENTITY);
CREATE TABLE memo_v2.runs(id text PRIMARY KEY, payload jsonb NOT NULL);
CREATE TABLE memo_v2.embeddings(item_id text REFERENCES memo_v2.items, model text NOT NULL, version text NOT NULL, body_hash text NOT NULL, metadata jsonb NOT NULL, embedding extensions.vector(1536) NOT NULL, PRIMARY KEY(item_id,model,version));
CREATE INDEX embeddings_hnsw ON memo_v2.embeddings USING hnsw(embedding extensions.vector_cosine_ops);
CREATE INDEX ON memo_v2.events(item_id,seq DESC);
CREATE INDEX ON memo_v2.events(reviewer,created);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['editions','items','membership','tokens','events','profiles','runs','embeddings'] LOOP
 EXECUTE format('ALTER TABLE memo_v2.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('REVOKE ALL ON memo_v2.%I FROM PUBLIC,anon,authenticated',t);
 END LOOP;
END $$;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA memo_v2 FROM PUBLIC,anon,authenticated;

-- Fixed-iteration digest comparison after indexed lookup; raw secrets are never compared/stored.
CREATE FUNCTION memo_v2.digest_equal(a text,b text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE result integer:=0; n integer; BEGIN
 IF length(a)<>64 OR length(b)<>64 THEN RETURN false; END IF;
 FOR n IN 1..64 LOOP result:=result | (ascii(substr(a,n,1)) # ascii(substr(b,n,1))); END LOOP;
 RETURN result=0;
END $$;
REVOKE ALL ON FUNCTION memo_v2.digest_equal(text,text) FROM PUBLIC,anon,authenticated;

-- Reject JSON strings, nonfinite/overflowing values, near-zero norms and wrong dimensions.
CREATE FUNCTION memo_v2.checked_vector(v jsonb) RETURNS extensions.vector LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,extensions AS $$
DECLARE val jsonb; n double precision; norm double precision:=0; normalized jsonb; BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'array' OR jsonb_array_length(v)<>1536 THEN RAISE EXCEPTION 'invalid embedding'; END IF;
 FOR val IN SELECT value FROM jsonb_array_elements(v) LOOP
   IF jsonb_typeof(val) IS DISTINCT FROM 'number' THEN RAISE EXCEPTION 'invalid embedding'; END IF;
   n:=(val::text)::double precision;
   IF abs(n)>1e20 OR n='NaN'::double precision THEN RAISE EXCEPTION 'invalid embedding'; END IF;
   norm:=norm+n*n;
 END LOOP;
 IF norm<1e-40 THEN RAISE EXCEPTION 'invalid embedding'; END IF;
 -- Normalize in bounded float64 arithmetic BEFORE converting to pgvector float32.
 -- Otherwise admitted large coordinates can overflow pgvector cosine accumulation.
 SELECT jsonb_agg((value::text)::double precision/sqrt(norm)) INTO normalized FROM jsonb_array_elements(v);
 RETURN normalized::text::extensions.vector;
END $$;
REVOKE ALL ON FUNCTION memo_v2.checked_vector(jsonb) FROM PUBLIC,anon,authenticated;

-- Edge passes SHA256 token digest, never the raw token. Only service_role can invoke.
CREATE FUNCTION public.memo_v2_dispatch(token_hash text, action text, args jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,memo_v2,extensions AS $$
DECLARE principal memo_v2.tokens%ROWTYPE; existing memo_v2.events%ROWTYPE; e jsonb; i jsonb; out jsonb; op text; a jsonb; labels jsonb; query_vector extensions.vector;
BEGIN
 SELECT * INTO principal FROM memo_v2.tokens WHERE hash=token_hash AND memo_v2.digest_equal(hash,token_hash) AND NOT revoked;
 IF NOT FOUND THEN RAISE EXCEPTION 'unauthorized' USING ERRCODE='28000'; END IF;
 IF action='edition' AND principal.role='reviewer' THEN
   SELECT payload INTO e FROM memo_v2.editions ORDER BY day DESC,seq DESC LIMIT 1;
   SELECT coalesce(jsonb_object_agg(x.id,coalesce(nullif((SELECT label FROM memo_v2.events WHERE item_id=x.id AND reviewer=principal.reviewer ORDER BY seq DESC LIMIT 1),'cleared'),'unlabeled')),'{}'::jsonb) INTO labels FROM jsonb_to_recordset(coalesce(e->'items','[]')) AS x(id text);
   RETURN jsonb_build_object('edition',e,'labels',labels);
 ELSIF action='feedback' AND principal.role='reviewer' THEN
   IF coalesce(args->>'item_id','')='' OR coalesce(args->>'edition_id','')='' OR coalesce(args->>'client_event_id','')='' OR coalesce(args->>'label','') NOT IN ('used','not_relevant','cleared') THEN RAISE EXCEPTION 'invalid feedback'; END IF;
   -- Serialize a reviewer's event stream so server order and rate checks are deterministic.
   PERFORM pg_advisory_xact_lock(hashtextextended(principal.reviewer,0));
   SELECT * INTO existing FROM memo_v2.events WHERE event_id=(args->>'client_event_id')::uuid;
   IF FOUND THEN
     IF existing.reviewer IS DISTINCT FROM principal.reviewer OR existing.item_id IS DISTINCT FROM args->>'item_id' OR existing.edition_id IS DISTINCT FROM args->>'edition_id' OR existing.label IS DISTINCT FROM args->>'label' THEN RAISE EXCEPTION 'event conflict'; END IF;
   ELSE
     IF (SELECT count(*) FROM memo_v2.events WHERE reviewer=principal.reviewer AND created>now()-interval '1 minute')>=60 THEN RAISE EXCEPTION 'rate limit'; END IF;
     INSERT INTO memo_v2.events(event_id,reviewer,edition_id,item_id,label) VALUES((args->>'client_event_id')::uuid,principal.reviewer,args->>'edition_id',args->>'item_id',args->>'label');
   END IF;
   RETURN jsonb_build_object('saved',true,'client_event_id',args->>'client_event_id','label',args->>'label');
 ELSIF action='ci' AND principal.role='ci' THEN
   op:=args->>'operation'; a:=args->'arguments';
   CASE op
   WHEN 'register_edition' THEN
     e:=a->'edition'; IF EXISTS(SELECT 1 FROM memo_v2.editions WHERE id=e->>'id' AND payload<>e) THEN RAISE EXCEPTION 'immutable edition conflict'; END IF; INSERT INTO memo_v2.editions(id,day,payload) VALUES(e->>'id',(e->>'edition_date')::date,e) ON CONFLICT DO NOTHING;
     FOR i IN SELECT value FROM jsonb_array_elements(e->'items') LOOP
       IF EXISTS(SELECT 1 FROM memo_v2.items WHERE id=i->>'id' AND (coalesce(payload->>'canonical_body',regexp_replace(trim(payload->>'body'),'\s+',' ','g')) IS DISTINCT FROM coalesce(i->>'canonical_body',regexp_replace(trim(i->>'body'),'\s+',' ','g')) OR payload->>'content_hash' IS DISTINCT FROM i->>'content_hash')) THEN RAISE EXCEPTION 'immutable item conflict'; END IF;
       INSERT INTO memo_v2.items VALUES(i->>'id',i) ON CONFLICT DO NOTHING;
       INSERT INTO memo_v2.membership VALUES(e->>'id',i->>'id') ON CONFLICT DO NOTHING;
     END LOOP;
   WHEN 'latest_edition' THEN SELECT payload INTO out FROM memo_v2.editions ORDER BY day DESC,seq DESC LIMIT 1;
   WHEN 'get_item' THEN SELECT payload INTO out FROM memo_v2.items WHERE id=a->>'item_id';
   WHEN 'get_item_feedback' THEN
     SELECT coalesce(jsonb_object_agg(x,coalesce(nullif((SELECT label FROM memo_v2.events WHERE item_id=x ORDER BY seq DESC LIMIT 1),'cleared'),'unlabeled')),'{}'::jsonb) INTO out FROM jsonb_array_elements_text(a->'item_ids') x;
   WHEN 'get_preference_profile' THEN
     SELECT payload INTO out FROM memo_v2.profiles WHERE a->>'version'='latest' OR version=a->>'version' ORDER BY seq DESC LIMIT 1; out:=coalesce(out,'{}');
   WHEN 'save_preference_profile' THEN
     i:=jsonb_build_object('approved_for_experiment',false)||(a->'profile'); INSERT INTO memo_v2.profiles(version,payload) VALUES(i->>'version',i);
   WHEN 'save_shadow_run' THEN
     i:=a->'run'; INSERT INTO memo_v2.runs VALUES(coalesce(i->>'id',i->>'run_id',gen_random_uuid()::text),i) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload;
   WHEN 'has_embedding' THEN
     SELECT to_jsonb(EXISTS(SELECT 1 FROM memo_v2.embeddings em JOIN memo_v2.items it ON it.id=em.item_id WHERE em.item_id=a->>'item_id' AND em.model=a->>'model' AND em.version=a->>'version' AND em.body_hash=it.payload->>'content_hash')) INTO out;
   WHEN 'add_embedding' THEN
     IF a->>'model'<>'text-embedding-3-small' OR coalesce(a->>'version','')='' OR jsonb_array_length(a->'vector')<>1536 THEN RAISE EXCEPTION 'invalid embedding'; END IF;
     query_vector:=memo_v2.checked_vector(a->'vector');
     SELECT payload INTO i FROM memo_v2.items WHERE id=a->>'item_id'; IF NOT FOUND THEN RAISE EXCEPTION 'unknown item'; END IF;
     INSERT INTO memo_v2.embeddings VALUES(a->>'item_id',a->>'model',a->>'version',i->>'content_hash',i,query_vector) ON CONFLICT(item_id,model,version) DO UPDATE SET body_hash=excluded.body_hash,metadata=excluded.metadata,embedding=excluded.embedding;
   WHEN 'search_history' THEN
     IF (a->>'date_from')::date>(a->>'date_to')::date THEN RAISE EXCEPTION 'invalid date range'; END IF;
     query_vector:=memo_v2.checked_vector(a->'vector');
     -- Bounded approximate search: direct distance order drives HNSW. Filters apply
     -- during candidate selection, then at most 200 candidates get recency reranking.
     PERFORM set_config('hnsw.iterative_scan','strict_order',true);
     PERFORM set_config('hnsw.max_scan_tuples','5000',true);
     PERFORM set_config('hnsw.ef_search','200',true);
     PERFORM set_config('enable_seqscan','off',true);
     PERFORM set_config('enable_sort','off',true);
     WITH candidates AS MATERIALIZED (
       SELECT em.item_id, em.body_hash, em.embedding OPERATOR(extensions.<=>) query_vector AS distance
       FROM memo_v2.embeddings em
       WHERE em.model=a->>'model' AND em.version=a->>'version'
       AND ((a->>'date_from') IS NULL OR (em.metadata->>'edition_date')::date>=(a->>'date_from')::date)
       AND ((a->>'date_to') IS NULL OR (em.metadata->>'edition_date')::date<=(a->>'date_to')::date)
       AND (coalesce(a->'tickers','null') IN ('null'::jsonb,'[]'::jsonb) OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(a->'tickers') t WHERE em.metadata->'tickers' ? t))
       AND (coalesce(a->'topics','null') IN ('null'::jsonb,'[]'::jsonb) OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(a->'topics') t WHERE em.metadata->'topics' ? t))
       ORDER BY em.embedding OPERATOR(extensions.<=>) query_vector LIMIT 200
     ), scored AS (
       SELECT it.payload, it.id, 1-c.distance AS similarity,
         1.0/(1+greatest(0,current_date-(it.payload->>'edition_date')::date)/30.0) AS recency
       FROM candidates c JOIN memo_v2.items it ON it.id=c.item_id AND c.body_hash=it.payload->>'content_hash'
     ), ranked AS (
       SELECT payload||jsonb_build_object('similarity',similarity,'retrieval_score',0.9*similarity+0.1*recency,'recency_score',recency,'history_only',true,
         'label',coalesce(nullif((SELECT label FROM memo_v2.events WHERE item_id=scored.id ORDER BY seq DESC LIMIT 1),'cleared'),'unlabeled')) AS payload,
         0.9*similarity+0.1*recency AS score
       FROM scored ORDER BY score DESC LIMIT greatest(1,least(50,coalesce((a->>'limit')::int,10)))
     ) SELECT coalesce(jsonb_agg(payload ORDER BY score DESC),'[]'::jsonb) INTO out FROM ranked;
   ELSE RAISE EXCEPTION 'forbidden operation';
   END CASE;
   RETURN jsonb_build_object('result',out);
 END IF;
 RAISE EXCEPTION 'forbidden' USING ERRCODE='42501';
END $$;
REVOKE ALL ON FUNCTION public.memo_v2_dispatch(text,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.memo_v2_dispatch(text,text,jsonb) TO service_role;
