"""Private prospective evaluation. Unlabeled items never become negative examples."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from .paths import private_directory
from scripts.trading_calendar import HKEX_HOLIDAYS, is_hk_trading_day


def evaluate(snapshot):
    """Score a saved ranking and explicit judgments, preserving missing evidence."""
    ranked = snapshot.get('ranked_item_ids', [])
    if len(ranked) != len(set(ranked)):
        raise ValueError('Ranking contains duplicate item IDs')
    events = snapshot.get('feedback_events', [])
    seen = set()
    latest = {}
    explicit = []
    for event in sorted(events, key=lambda e: e['server_sequence']):
        if event.get('provenance') != 'explicit_feedback':
            continue
        if event['event_id'] in seen:
            continue
        if event['label'] not in ('used', 'not_relevant', 'cleared'):
            raise ValueError('Invalid explicit label')
        datetime.strptime(event['edition_date'], '%Y-%m-%d')
        seen.add(event['event_id'])
        explicit.append(event)
        latest[event['item_id']] = event
    labels = {item: event['label'] for item, event in latest.items()}
    result = {'schema_version': 1, 'edition_date': snapshot.get('edition_date'),
              'ranking_count': len(ranked), 'source_snapshot': snapshot.get('source_snapshot'),
              'promotion_authorized': False}
    for k in (5, 10):
        ids = ranked[:k]
        used = sum(labels.get(item) == 'used' for item in ids)
        rejected = sum(labels.get(item) == 'not_relevant' for item in ids)
        n = len(ids)
        known = used + rejected
        result[f'top_{k}'] = {
            'items': n, 'used': used, 'not_relevant': rejected, 'unknown': n-known,
            'label_coverage': known/n if n else None,
            # With incomplete judgments, precision over all candidates is unidentified.
            'used_precision': used/n if n and known == n else None,
            'not_relevant_rate': rejected/n if n and known == n else None,
            'used_rate_among_labeled': used/known if known else None,
            'used_precision_bounds': [used/n, (used+n-known)/n] if n else None,
        }
    used_ranks = []
    for match in snapshot.get('reviewed_v1_matches', []):
        if match.get('confirmed') is not True or labels.get(match.get('v1_item_id')) != 'used':
            continue
        target = match.get('v2_item_id')
        used_ranks.append({'v1_item_id': match['v1_item_id'], 'v2_item_id': target,
                          'v2_rank': ranked.index(target)+1 if target in ranked else None})
    result['used_v1_story_ranks'] = used_ranks
    labeled_dates = {e['edition_date'] for e in latest.values() if e['label'] != 'cleared'}
    dates = [datetime.strptime(value, '%Y-%m-%d').date() for value in labeled_dates]
    verified_dates = {day for day in dates if day.year in HKEX_HOLIDAYS and is_hk_trading_day(day)}
    result['formal_review'] = {'explicit_events': len(explicit), 'labeled_trading_editions': len(verified_dates),
                               'unverified_calendar_editions': sum(day.year not in HKEX_HOLIDAYS for day in dates),
                               'eligible': len(explicit) >= 100 and len(verified_dates) >= 20}
    checks = snapshot.get('reviewed_checks', {})
    for field in ('stale_or_repeated', 'citations_supported', 'retrieval_relevant', 'copied_without_edit'):
        values = checks.get(field, [])
        known = [v for v in values if isinstance(v, bool)]
        result[field] = {'reviewed': len(known), 'unknown': len(values)-len(known),
                         'rate_among_reviewed': sum(known)/len(known) if known else None}
    result['generation_seconds'] = None
    if snapshot.get('started_at') and snapshot.get('finished_at'):
        start, finish = (datetime.fromisoformat(snapshot[key]) for key in ('started_at','finished_at'))
        if start.tzinfo is None or finish.tzinfo is None or finish < start:
            raise ValueError('Invalid observed runtime')
        result['generation_seconds'] = (finish-start).total_seconds()
    result['estimated_cost_usd'] = snapshot.get('estimated_cost_usd')
    result['actual_invoice_usd'] = snapshot.get('actual_invoice_usd')
    result['editing_minutes'] = snapshot.get('editing_minutes')
    result['on_time'] = snapshot.get('independent_on_time_observation')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, help='Private saved ranking/judgments JSON')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    snapshot = json.loads(Path(args.snapshot).read_text())
    output = private_directory(args.output_dir) / 'prospective-evaluation.json'
    output.write_text(json.dumps(evaluate(snapshot), indent=2))
    output.chmod(0o600)
    print('Private evaluation saved; no production promotion is permitted.')


if __name__ == '__main__':
    main()
