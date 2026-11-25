"""Deterministic identities for public source editions; never invent metadata."""
import hashlib
import json
import re
import unicodedata
from datetime import date


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split())


TAGGER_VERSION = 'keyword-v1'
TOPIC_TERMS = {
    'buybacks': ('buyback', 'repurchase'), 'earnings': ('earnings', 'net profit', 'quarterly results'),
    'semiconductors': ('semiconductor', 'chip testing', 'chipmaker'),
    'artificial_intelligence': ('generative', 'ai model', 'ai-model', 'ai-server', 'ai-computing', 'artificial intelligence'),
    'commodities': ('crude', 'brent', 'gold', 'copper', 'lithium'),
    'macroeconomics': ('treasury', 'inflation', 'job openings', 'consumer confidence'),
    'corporate_transactions': ('acquire', 'acquisition', 'merger'),
}
COMPANY_ALIASES = {'Tencent': ('tencent',), 'Alibaba': ('alibaba',), 'Nvidia': ('nvidia',), 'Apple': ('apple',), 'Tesla': ('tesla',), 'Meta': ('meta',)}


def tags(body):
    text = body.lower()
    topics = [name for name, terms in TOPIC_TERMS.items() if any(re.search(r'\b'+re.escape(term)+r'\b', text) for term in terms)]
    companies = [name for name, aliases in COMPANY_ALIASES.items() if any(re.search(r'\b'+re.escape(alias)+r'\b',text) for alias in aliases)]
    # Explicit source strings only; no inferred mapping from company to ticker.
    tickers = set(re.findall(r'\b\d{1,6} (?:HK|CH)\b',body))
    tickers.update(re.findall(r'\((?:NASDAQ|NYSE):\s*([A-Z]{1,5}(?:\.[A-Z])?)\)',body))
    tickers.update(re.findall(r'(?<!\w)\$([A-Z]{1,5})\b',body))
    sectors = sorted(set({'semiconductors':'technology','artificial_intelligence':'technology','commodities':'materials'}[t] for t in topics if t in ('semiconductors','artificial_intelligence','commodities')))
    return companies, sorted(tickers), topics, sectors


def parse_edition(markdown: str, edition_date: str, source_version: str = '') -> dict:
    date.fromisoformat(edition_date)
    bodies = re.findall(r'^[-*] +(.+?)(?=^[-*] +|\Z)', markdown, re.M | re.S)
    items = []
    for body in bodies:
        body = body.strip()
        urls = sorted(set(re.findall(r'https?://[^\s<>\])]+', body)))
        content_hash = digest(normalize(body))
        item_id = digest(json.dumps([edition_date, normalize(body), urls], ensure_ascii=False))
        if any(i['id'] == item_id for i in items):
            continue
        companies, tickers, topics, sectors = tags(body)
        headline = re.match(r'\*\*(.+?)\*\*', body)
        items.append(dict(id=item_id, edition_date=edition_date, position=len(items),
                          headline=headline.group(1).rstrip(':') if headline else body.split('\n')[0],
                          body=body, canonical_body=normalize(body), source_urls=urls, companies=companies, tickers=tickers,
                          topics=topics, sectors=sectors, tagger_version=TAGGER_VERSION, content_hash=content_hash))
    cutoff = next((line.strip() for line in markdown.splitlines() if 'research cutoff' in line.lower()), '')
    return dict(id=digest(json.dumps([edition_date, source_version, digest(markdown)])),
                edition_date=edition_date, research_cutoff=cutoff,
                source_version=source_version, prompt_version='', items=items)
