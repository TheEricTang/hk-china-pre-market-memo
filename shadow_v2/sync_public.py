"""Refresh the private reviewer from a hash-verified public publication receipt."""
import hashlib
import json
import os
import re
import time
import uuid
import urllib.request
from datetime import date
from .models import parse_edition
from .paths import REPOSITORY
from .supabase_store import SupabaseStore

PUBLIC_SITE = 'https://theerictang.github.io/hk-china-pre-market-memo/'
PUBLIC_MEMOS = 'https://raw.githubusercontent.com/TheEricTang/hk-china-pre-market-memo/main/memos/'


def fetch_bytes(url, timeout):
    request = urllib.request.Request(url + '?v2_receipt=' + uuid.uuid4().hex,
                                     headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_001)


def verified_public_edition(fetch=fetch_bytes, seconds=55, sleep=time.sleep, clock=time.monotonic):
    """No writes occur until receipt, published Markdown and fresh checkout agree."""
    expected = json.loads((REPOSITORY / 'docs' / 'status.json').read_text())
    deadline = clock() + min(seconds, 55)
    while clock() < deadline:
        try:
            receipt = json.loads(fetch(PUBLIC_SITE + 'status.json', min(10, deadline-clock())))
            day, digest = receipt['editionDate'], receipt['memoSha256']
            if any(receipt.get(key) != expected.get(key) for key in ('editionDate', 'memoSha256')):
                raise ValueError('public receipt has not caught up to checkout')
            date.fromisoformat(day)
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or not re.fullmatch(r'[a-f0-9]{64}', digest):
                raise ValueError('invalid public receipt')
            remaining = deadline-clock()
            if remaining <= 0:
                break
            published = fetch(PUBLIC_MEMOS + f'memo-{day}.md', min(10, remaining))
            candidate = (REPOSITORY / 'memos' / f'memo-{day}.md').read_bytes()
            if len(published) > 2_000_000 or hashlib.sha256(published).hexdigest() != digest:
                raise ValueError('public Markdown differs from receipt')
            if hashlib.sha256(candidate).hexdigest() != digest:
                raise ValueError('checkout differs from published edition')
            edition = parse_edition(candidate.decode('utf-8'), day, 'sha256:' + digest)
            if not edition['items']:
                raise ValueError('empty published edition')
            return edition
        except Exception:
            remaining = deadline-clock()
            if remaining <= 0:
                break
            sleep(min(3, remaining))
    raise RuntimeError('public edition verification failed; previous private edition preserved')


def sync_public(store, **verification_options):
    edition = verified_public_edition(**verification_options)
    store.register_edition(edition)
    return edition


def main():
    store = SupabaseStore(os.environ['V2_BACKEND_URL'], os.environ['V2_CI_TOKEN'])
    sync_public(store)
    print(json.dumps({'registered_public_editions': 1}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"status":"failed","error":"public_archive_registration_failed"}')
        raise SystemExit(2)
