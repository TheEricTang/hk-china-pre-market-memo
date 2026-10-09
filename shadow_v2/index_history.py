"""Explicit, budgeted semantic indexing of the public archive only."""
import argparse
import hashlib
import json
import math
import os
import re
import uuid
from .models import parse_edition
from .paths import REPOSITORY, private_path, private_directory
from .store import Store
from .supabase_store import SupabaseStore
from .embeddings import OpenAIEmbeddingAdapter
from .policy import Budget


def embedding_text(item):
    body=re.sub(r'https?://[^\s)]+','',item['body'])
    return re.sub(r'https?://[^\s)]+','', '\n'.join([item['headline'],body,' '.join(item['companies']+item['sectors']+item['topics'])]))


def index_archive(store,adapter,budget,rate,max_items=200):
    if not math.isfinite(rate) or rate<=0 or not 1<=max_items<=200:
        raise ValueError('Invalid indexing limits')
    count=0
    for memo in reversed(sorted((REPOSITORY/'memos').glob('memo-????-??-??.md'))):
        markdown=memo.read_text()
        version='sha256:'+hashlib.sha256(markdown.encode()).hexdigest()
        edition=parse_edition(markdown,memo.stem[5:],version)
        for item in edition['items']:
            # Never import an unpublished checkout item as a side effect of paid indexing.
            if not store.get_item(item['id']):
                continue
            if store.has_embedding(item['id'], adapter.model, adapter.version):
                continue
            if count>=max_items:return count
            text=embedding_text(item)
            # UTF-8 bytes bound tokenizer tokens; reserve both attempts allowed by adapter.
            maximum=2*len(text.encode())*rate/1_000_000
            reservation=budget.reserve('archive_embedding',maximum)
            vector=adapter.embed(text)
            tokens=adapter.last_usage.get('total_tokens')
            estimated=tokens*rate/1_000_000 if isinstance(tokens,int) and tokens>0 else maximum
            budget.settle(reservation,estimated,{'tokens':tokens,'billing':'configured_rate_estimate','actual_invoice_usd':None})
            store.add_embedding(item['id'],vector,adapter.model,adapter.version)
            count+=1
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    backend=parser.add_mutually_exclusive_group(required=True)
    backend.add_argument('--store');backend.add_argument('--cloud',action='store_true')
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--rate-usd-per-million',type=float)
    parser.add_argument('--budget-usd',type=float,default=1)
    parser.add_argument('--max-items',type=int,default=200)
    args=parser.parse_args()
    directory=private_directory(args.output_dir)
    store=Store(str(private_path(args.store))) if args.store else SupabaseStore(os.environ['V2_BACKEND_URL'],os.environ['V2_CI_TOKEN'])
    if not 0 <= args.budget_usd <= 1:
        raise ValueError('Indexing budget must not exceed $1')
    rate = args.rate_usd_per_million
    if rate is None:
        rate = float(json.loads(os.environ['V2_RATE_CARD'])['embedding_per_million'])
    budget=Budget(args.budget_usd,600)
    try:
        count=index_archive(store,OpenAIEmbeddingAdapter(),budget,rate,args.max_items)
        result={'status':'complete','indexed':count,'cost_estimate_usd':budget.spent,'usage':budget.calls}
    except Exception:
        result={'status':'failed','cost_estimate_usd':budget.spent,'usage':budget.calls}
    result.update(id='index-'+uuid.uuid4().hex, kind='archive_index', reserved_estimate_usd=budget.reserved, actual_invoice_usd=None)
    store.save_shadow_run(result)
    path=directory/'indexing-result.json'
    path.write_text(json.dumps(result,indent=2));path.chmod(0o600)
    print(json.dumps({k:v for k,v in result.items() if k!='usage'}))
    return 0 if result['status']=='complete' else 2


if __name__=='__main__':raise SystemExit(main())
