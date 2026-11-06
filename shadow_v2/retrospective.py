"""Private, local proposals from Cindy's saved email editions.

This is a comparison aid, not evidence that Cindy saw or used a site edition.
No feedback events are written by this module.
"""
import argparse
import hashlib
import html
import json
import re
import subprocess
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .models import digest, parse_edition
from .paths import REPOSITORY, private_directory, private_path
from .store import Store

HKT = ZoneInfo('Asia/Hong_Kong')
URL = re.compile(r'https?://[^\s<>\])]+', re.I)
TICKER = re.compile(r'\b\d{1,6}\s+(?:HK|CH)\b', re.I)
QUOTED = re.compile(r'^(?:>|On .+ wrote:|From:|Sent:|To:|Cc:|Subject:)', re.I)
SIGNATURE = re.compile(r'^(?:--\s*$|Best regards[,!]?|Kind regards[,!]?|Regards[,!]?|Sent from my |Confidentiality notice)', re.I)
TOKENS = re.compile(r'[\w\u4e00-\u9fff]+', re.UNICODE)
NUMBERS = re.compile(r'\b\d+(?:[.,]\d+)*%?\b')


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
        self.quote = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'blockquote' or 'gmail_quote' in attrs.get('class', ''):
            self.quote += 1
        if tag in ('p', 'div', 'li', 'br') and not self.hidden and not self.quote:
            self.parts.append('\n\n' if tag != 'br' else '\n')
        if tag == 'a' and not self.hidden and not self.quote and attrs.get('href', '').startswith(('http://', 'https://')):
            self.parts.append(' ')
            self.parts.append(attrs['href'])
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        if tag == 'blockquote' and self.quote:
            self.quote -= 1
        if tag in ('p', 'div', 'li') and not self.hidden and not self.quote:
            self.parts.append('\n\n')

    def handle_data(self, data):
        if not self.hidden and not self.quote:
            self.parts.append(data)

    def text(self):
        return html.unescape(''.join(self.parts))


def _body(message):
    plain = message.get_body(preferencelist=('plain',))
    if plain is not None:
        return plain.get_content()
    rich = message.get_body(preferencelist=('html',))
    if rich is None:
        raise ValueError('Email has no plain or HTML body')
    parser = _HTMLText()
    parser.feed(rich.get_content())
    return parser.text()


def _paragraphs(raw):
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    cleaned = []
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if QUOTED.match(line) or SIGNATURE.match(line):
            break
        if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', line):
            # Addresses, and the surrounding header line, are not content.
            continue
        cleaned.append((number, line))
    groups, current = [], []
    for number, line in cleaned + [(len(lines) + 1, '')]:
        if line:
            current.append((number, line))
        elif current:
            text = ' '.join(part for _, part in current)
            if text and not re.fullmatch(r'[_\-\s]{3,}', text):
                groups.append((current[0][0], text))
            current = []
    return groups


def parse_email(path: Path):
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    stamp = parsedate_to_datetime(message['Date'])
    if stamp is None or stamp.tzinfo is None:
        raise ValueError(f'Missing timezone-aware Date header: {path.name}')
    local = stamp.astimezone(HKT)
    items = []
    for index, (line, body) in enumerate(_paragraphs(_body(message)), 1):
        items.append(dict(id=digest(json.dumps([path.name, local.date().isoformat(), index, body], ensure_ascii=False)),
                          position=index, line=line, body=body, urls=extract_urls(body),
                          tickers=sorted(set(t.upper() for t in TICKER.findall(body)))))
    return dict(file=path.name, date=local.date().isoformat(),
                email_at=stamp.astimezone(timezone.utc).isoformat(), subject=str(message.get('Subject', '')),
                items=items)


def canonical_url(value):
    value = html.unescape(value).rstrip('.,;:')
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/') or '/', '', ''))


def extract_urls(text):
    return sorted(set(canonical_url(value) for value in URL.findall(text)))


def _tokens(text):
    text = URL.sub(' ', text)
    return set(t.casefold() for t in TOKENS.findall(text) if len(t) > 2)


def similarity(left, right):
    a, b = _tokens(left), _tokens(right)
    jaccard = len(a & b) / len(a | b) if a and b else 0.0
    sequence = SequenceMatcher(None, re.sub(r'\s+', ' ', URL.sub('', left)).casefold(),
                               re.sub(r'\s+', ' ', URL.sub('', right)).casefold()).ratio()
    return round(max(jaccard, sequence * .8), 4)


def _site_items(path, day):
    markdown = path.read_text(encoding='utf-8')
    edition = parse_edition(markdown, day, source_version='public-archive')
    starts = [i for i, line in enumerate(markdown.splitlines(), 1) if re.match(r'^[-*] +', line)]
    for item, line in zip(edition['items'], starts):
        item['line'] = line
    return edition['items']


def _snapshot(path):
    # A commit timestamp is evidence of that exact file snapshot, not public availability.
    result = subprocess.run(['git', 'log', '-1', '--format=%cI', '--', str(path)],
                            cwd=REPOSITORY, capture_output=True, text=True, check=False)
    if result.returncode or not result.stdout.strip():
        return None
    try:
        return datetime.fromisoformat(result.stdout.strip()).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def match_item(item, site_items):
    candidates = []
    for site in site_items:
        shared_urls = sorted(set(item['urls']) & {canonical_url(u) for u in site['source_urls']})
        shared_tickers = sorted(set(item['tickers']) & set(site['tickers']))
        sim = similarity(item['body'], site['body'])
        score = round((.72 if shared_urls else 0) + .25 * sim + (.08 if shared_tickers else 0), 4)
        if shared_urls or (shared_tickers and sim >= .42) or sim >= .72:
            candidates.append((score, sim, shared_urls, shared_tickers, site))
    candidates.sort(key=lambda row: row[0], reverse=True)
    if not candidates:
        return dict(classification='unmatched', confidence=0.0, reason='no sufficiently specific same-date candidate',
                    site_item_id=None, site_line=None, site_position=None)
    score, sim, urls, tickers, site = candidates[0]
    if len(candidates) > 1 and candidates[1][0] >= score - .08:
        return dict(classification='unmatched', confidence=round(score, 3), reason='ambiguous same-date candidates',
                    site_item_id=None, site_line=None, site_position=None,
                    candidate_item_ids=[row[4]['id'] for row in candidates[:3]])
    if sim >= .92 or (urls and sim >= .72):
        kind = 'exact'
    elif sim >= .65 or (urls and sim >= .38):
        kind = 'near'
    else:
        kind = 'rewritten'
    return dict(classification=kind, confidence=round(score, 3), reason='shared URL' if urls else 'text and explicit ticker similarity',
                shared_urls=urls, shared_tickers=tickers, text_similarity=sim,
                site_item_id=site['id'], site_line=site.get('line'), site_position=site['position'] + 1)


def import_retrospective(emails_dir, public_archive, output_dir, version='retrospective-v1'):
    emails_dir = Path(emails_dir).resolve()
    public_archive = Path(public_archive).resolve()
    output = private_directory(output_dir)
    if not emails_dir.is_dir() or not public_archive.is_dir():
        raise ValueError('Email and public-archive directories must exist')
    messages = [parse_email(path) for path in sorted(emails_dir.glob('*.eml'))]
    rows = []
    for message in messages:
        path = public_archive / f"memo-{message['date']}.md"
        sites = _site_items(path, message['date']) if path.exists() else []
        snapshot = _snapshot(path) if path.exists() else None
        before_email = bool(snapshot and datetime.fromisoformat(snapshot) < datetime.fromisoformat(message['email_at']))
        for item in message['items']:
            matched = match_item(item, sites)
            # No historical public availability proof: even a pre-email commit is only a
            # known local snapshot. Keep every result proposed and unapproved.
            rows.append(dict(email_file=message['file'], email_date=message['date'], email_at=message['email_at'],
                             email_item_id=item['id'], email_position=item['position'], email_line=item['line'],
                             email_body=item['body'], source_urls=item['urls'], explicit_tickers=item['tickers'],
                             site_archive_present=bool(sites), site_snapshot_commit_at=snapshot,
                             known_snapshot_predates_email=before_email, source_availability='unknown',
                             **matched))
    counts = {kind: sum(row['classification'] == kind for row in rows)
              for kind in ('exact', 'near', 'rewritten', 'unmatched')}
    strong = [row['email_item_id'] for row in rows if row['classification'] in ('exact', 'near')
              and row['confidence'] >= .85 and row['known_snapshot_predates_email']]
    proposal = dict(version=version, approved_for_experiment=False, source='local Cindy .eml retrospective',
                    evidence_file='matches.json', counts=dict(email_files=len(messages), email_items=len(rows), **counts),
                    proposed_retained_match_item_ids=strong,
                    claim='Proposed high-confidence retained matches only; no actual feedback or omitted-item negatives inferred.',
                    historical_public_availability='unknown')
    (output / 'matches.json').write_text(json.dumps(dict(version=version, messages=[{k:v for k,v in m.items() if k != 'items'} for m in messages],
                                                        rows=rows, counts=proposal['counts']), indent=2, ensure_ascii=False) + '\n')
    (output / 'preference-proposal.json').write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + '\n')
    for path in (output / 'matches.json', output / 'preference-proposal.json'):
        path.chmod(0o600)
    return proposal


def import_reviewed_profile(reviewed_file, store_file):
    reviewed_path = private_path(reviewed_file)
    destination = private_path(store_file)
    reviewed = json.loads(reviewed_path.read_text())
    if reviewed.get('confirmed') is not True or reviewed.get('approved_for_experiment') is not True:
        raise ValueError('Reviewed profile needs explicit confirmed=true and approved_for_experiment=true')
    if not reviewed.get('version'):
        raise ValueError('Reviewed profile needs a version')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Store(str(destination)) as store:
        store.save_preference_profile(reviewed)


def corpus_snapshot(emails_dir, public_archive, reviewed_audit):
    """Bind a reviewed index map to the exact source bytes and parsed positions."""
    emails_dir, public_archive = Path(emails_dir).resolve(), Path(public_archive).resolve()
    reviewed_audit = private_path(reviewed_audit)
    audit = json.loads(reviewed_audit.read_text())
    if not isinstance(audit, list):
        raise ValueError('Reviewed audit must be a list')
    messages = {path.name: parse_email(path) for path in sorted(emails_dir.glob('*.eml'))}
    if not messages:
        raise ValueError('No emails found')
    days = {message['date'] for message in messages.values()}
    sites = {}
    for day in days:
        path = public_archive / f'memo-{day}.md'
        if path.exists():
            sites[day] = _site_items(path, day)
    snapshot = dict(schema_version=1,
                    audit_sha256=hashlib.sha256(reviewed_audit.read_bytes()).hexdigest(),
                    emails={name:dict(date=message['date'],
                                      file_sha256=hashlib.sha256((emails_dir / name).read_bytes()).hexdigest(),
                                      item_hashes=[digest(item['body']) for item in message['items']])
                            for name,message in sorted(messages.items())},
                    sites={day:dict(file_sha256=hashlib.sha256((public_archive / f'memo-{day}.md').read_bytes()).hexdigest(),
                                    item_hashes=[digest(item['body']) for item in items])
                           for day,items in sorted(sites.items())})
    keys = set()
    for row in audit:
        name, day, position = row.get('email_file'), row.get('date'), row.get('email_item')
        if name not in messages or day != messages[name]['date'] or not isinstance(position, int) or isinstance(position, bool):
            raise ValueError('Reviewed audit email date or file mismatch')
        items = messages[name]['items']
        if position < 1 or position > len(items) or (name, position) in keys:
            raise ValueError('Reviewed audit has duplicate or invalid email item index')
        keys.add((name, position))
        label = _tokens(row.get('story_label', ''))
        body_tokens = _tokens(items[position - 1]['body'])
        if not label or len(label & body_tokens) / len(label) < .8:
            raise ValueError(f'Reviewed story label does not identify email paragraph: {name} #{position}')
        status, site_position = row.get('status'), row.get('site_item')
        if status not in ('Same', 'Partial', 'Missing', 'Unpaired'):
            raise ValueError('Unknown manual status')
        if status in ('Same', 'Partial'):
            if not isinstance(site_position, int) or isinstance(site_position, bool) or not 1 <= site_position <= len(sites.get(day, [])):
                raise ValueError('Invalid site item for paired status')
        elif site_position is not None:
            raise ValueError('Nonpaired status must not name site item')
        if status == 'Unpaired' and day in sites:
            raise ValueError('Unpaired date has a public archive')
        if status == 'Missing' and day not in sites:
            raise ValueError('Missing requires a same-date public archive')
    expected = {(name, i) for name,m in messages.items() for i in range(1,len(m['items']) + 1)}
    if keys != expected:
        raise ValueError('Reviewed audit does not cover every email paragraph exactly once')
    return snapshot, audit, messages, sites


def write_snapshot_manifest(emails_dir, public_archive, reviewed_audit, manifest_path):
    manifest_path = private_path(manifest_path)
    snapshot, _, _, _ = corpus_snapshot(emails_dir, public_archive, reviewed_audit)
    manifest_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path.write_text(json.dumps(dict(version='reviewed-corpus-v1', snapshot=snapshot),
                                        ensure_ascii=False, indent=2) + '\n')
    manifest_path.chmod(0o600)
    return snapshot


def import_reviewed_audit(emails_dir, public_archive, reviewed_audit, snapshot_manifest,
                          output_dir, version='reviewed-comparison-v1'):
    snapshot, audit, messages, sites = corpus_snapshot(emails_dir, public_archive, reviewed_audit)
    manifest = json.loads(private_path(snapshot_manifest).read_text())
    if manifest.get('version') != 'reviewed-corpus-v1' or manifest.get('snapshot') != snapshot:
        raise ValueError('Reviewed audit/corpus differs from saved content-hash manifest')
    output = private_directory(output_dir)
    mapped = []
    for row in audit:
        message = messages[row['email_file']]
        item = message['items'][row['email_item'] - 1]
        site = sites.get(row['date'], [])[row['site_item'] - 1] if row['site_item'] is not None else None
        email_numbers = set(NUMBERS.findall(URL.sub(' ', item['body'])))
        site_numbers = set(NUMBERS.findall(URL.sub(' ', site['body']))) if site else set()
        mapped.append(dict(email_file=row['email_file'], date=row['date'], email_at=message['email_at'],
                           email_position=row['email_item'], email_line=item['line'], email_item_id=item['id'],
                           email_body_hash=digest(item['body']), story_label=row['story_label'],
                           manual_status=row['status'], manual_note=row.get('note', ''),
                           site_position=row['site_item'], site_line=site.get('line') if site else None,
                           site_item_id=site['id'] if site else None,
                           site_body_hash=digest(site['body']) if site else None,
                           copy_fields=dict(email_only_explicit_tickers=sorted(set(item['tickers']) - set(site['tickers'])) if site else [],
                                            email_only_numbers=sorted(email_numbers - site_numbers)[:20] if site else []),
                           source_contained_at_email_time='unknown',
                           historical_public_availability='unknown', actual_feedback='unknown'))
    counts = {status:sum(row['manual_status'] == status for row in mapped)
              for status in ('Same','Partial','Missing','Unpaired')}
    result = dict(version=version, approved_for_experiment=False,
                  provenance=dict(reviewed_audit=str(private_path(reviewed_audit)),
                                  snapshot_manifest=str(private_path(snapshot_manifest)),
                                  audit_sha256=snapshot['audit_sha256']),
                  counts=counts, email_items=len(mapped),
                  interpretation='Manually reviewed historical comparison; not observed use or feedback.',
                  rows=mapped)
    path = output / 'reviewed-comparison.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)
    by_day = sorted({row['date'] for row in mapped})
    lines = [f'# Cindy manual comparison — {version}', '',
             f"Validated {len(mapped)} email paragraphs against a saved content-hash manifest.",
             f"Manual categories: Same {counts['Same']}; Partial {counts['Partial']}; "
             f"Missing {counts['Missing']}; Unpaired {counts['Unpaired']}.", '',
             'These are retrospective story comparisons, not observed use, approval, or negative feedback.',
             'Every source-availability and historical public-availability value remains unknown.',
             'The copy fields below are literal differences between the saved email and site text. '
             'They are opportunities only if the source contained the fact before the memo cutoff.', '',
             '| Date | Same | Partial | Missing | Unpaired |',
             '|---|---:|---:|---:|---:|']
    for day in by_day:
        subset = [row for row in mapped if row['date'] == day]
        counts_day = {kind:sum(row['manual_status'] == kind for row in subset)
                      for kind in ('Same','Partial','Missing','Unpaired')}
        lines.append(f"| {day} | {counts_day['Same']} | {counts_day['Partial']} | "
                     f"{counts_day['Missing']} | {counts_day['Unpaired']} |")
    lines += ['', '## Partial overlaps and candidate copy fields', '',
              '| Email item | Site item | Manual note | Email-only explicit fields |',
              '|---|---|---|---|']
    for row in mapped:
        if row['manual_status'] != 'Partial':
            continue
        copy = row['copy_fields']
        fields = ', '.join(copy['email_only_explicit_tickers'] + copy['email_only_numbers'][:8]) or 'none identified'
        note = row['manual_note'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {row['date']} #{row['email_position']} {row['story_label'].replace('|', '/')} "
                     f"| #{row['site_position']} | {note} | {fields} |")
    lines += ['', 'The full 164-row mapping, stable item IDs, lines, hashes, and notes are in '
              '`reviewed-comparison.json`. This report does not create Store feedback events or '
              'approve a preference profile.', '']
    report = output / 'reviewed-comparison.md'
    report.write_text('\n'.join(lines), encoding='utf-8')
    report.chmod(0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emails-dir', type=Path)
    parser.add_argument('--public-archive', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--version', default='retrospective-v1')
    parser.add_argument('--reviewed-file', type=Path)
    parser.add_argument('--store', type=Path)
    parser.add_argument('--reviewed-audit', type=Path)
    parser.add_argument('--snapshot-manifest', type=Path)
    parser.add_argument('--write-snapshot-manifest', type=Path)
    args = parser.parse_args()
    if args.reviewed_file or args.store:
        if not (args.reviewed_file and args.store):
            parser.error('--reviewed-file and --store must be supplied together')
        import_reviewed_profile(args.reviewed_file, args.store)
        print('Explicitly reviewed preference profile saved.')
        return
    if args.write_snapshot_manifest:
        if not (args.emails_dir and args.public_archive and args.reviewed_audit):
            parser.error('Manifest generation requires --emails-dir, --public-archive and --reviewed-audit')
        write_snapshot_manifest(args.emails_dir, args.public_archive, args.reviewed_audit, args.write_snapshot_manifest)
        print('Private content-hash manifest saved.')
        return
    if args.reviewed_audit:
        if not (args.emails_dir and args.public_archive and args.snapshot_manifest and args.output_dir):
            parser.error('Reviewed audit import requires email/archive/output directories and --snapshot-manifest')
        result = import_reviewed_audit(args.emails_dir, args.public_archive, args.reviewed_audit,
                                       args.snapshot_manifest, args.output_dir, args.version)
        print(json.dumps(result['counts']))
        return
    if not (args.emails_dir and args.public_archive and args.output_dir):
        parser.error('--emails-dir, --public-archive and --output-dir are required')
    profile = import_retrospective(args.emails_dir, args.public_archive, args.output_dir, args.version)
    print(json.dumps(profile['counts']))


if __name__ == '__main__':
    main()
