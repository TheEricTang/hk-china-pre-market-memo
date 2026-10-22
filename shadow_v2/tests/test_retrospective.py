import json
import tempfile
import unittest
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from shadow_v2.retrospective import (import_retrospective, import_reviewed_profile,
                                     import_reviewed_audit, match_item, parse_email,
                                     write_snapshot_manifest)
from shadow_v2.paths import REPOSITORY


def email_file(path, date, body=None, html=None):
    message = EmailMessage()
    message['Date'] = date
    message['From'] = 'person@example.com'
    message['Subject'] = 'selective headlines'
    if body is not None:
        message.set_content(body)
    else:
        message.set_content('Fallback')
    if html is not None:
        message.add_alternative(html, subtype='html')
    path.write_bytes(message.as_bytes())


class RetrospectiveTests(unittest.TestCase):
    def test_date_comes_from_hkt_header_not_filename(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'selective headlines 9_3 (1).eml'
            email_file(path, 'Thu, 03 Sep 2026 23:45:46 +0000',
                       'One story: Nvidia. [source<https://example.com/one>]')
            parsed = parse_email(path)
            self.assertEqual(parsed['date'], '2026-09-04')
            self.assertEqual(len(parsed['items']), 1)

    def test_html_fallback_and_quoted_footer_removed(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'email.eml'
            message = EmailMessage()
            message['Date'] = 'Thu, 03 Sep 2026 23:45:46 +0000'
            message.set_content('<p>New story <a href="https://example.com/a">source</a></p>'
                                '<blockquote>Old story</blockquote><p>Second story</p>', subtype='html')
            path.write_bytes(message.as_bytes())
            parsed = parse_email(path)
            self.assertEqual(len(parsed['items']), 2)
            self.assertIn('https://example.com/a', parsed['items'][0]['urls'])
            plain = Path(root) / 'plain.eml'
            email_file(plain, 'Thu, 03 Sep 2026 23:45:46 +0000',
                       'Good story\n\nBest regards,\nCindy\n\nOn Tue wrote:\nOld story')
            self.assertEqual(len(parse_email(plain)['items']), 1)

    def test_ambiguous_source_bundle_stays_unmatched(self):
        email = dict(body='China company news', urls=['https://example.com/bundle'], tickers=[])
        sites = [
            dict(id='a', body='Company A news', source_urls=['https://example.com/bundle'], tickers=[], position=0),
            dict(id='b', body='Company B news', source_urls=['https://example.com/bundle'], tickers=[], position=1),
        ]
        self.assertEqual(match_item(email, sites)['reason'], 'ambiguous same-date candidates')

    def test_identical_story_is_exact_without_url(self):
        email = dict(body='Company A reports a new product launch today.', urls=[], tickers=[])
        site = dict(id='a', body=email['body'], source_urls=[], tickers=[], position=0)
        self.assertEqual(match_item(email, [site])['classification'], 'exact')

    def test_cross_date_rejection_unknown_availability_and_no_auto_labels(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            emails, public, output = (root / name for name in ('emails', 'public', 'private'))
            emails.mkdir(); public.mkdir()
            email_file(emails / 'wrong_name.eml', 'Thu, 03 Sep 2026 23:45:46 +0000',
                       'Company A: new product. [source<https://example.com/a>]')
            (public / 'memo-2026-09-03.md').write_text(
                '- **Company A:** new product. [source](https://example.com/a)\n')
            profile = import_retrospective(emails, public, output)
            row = json.loads((output / 'matches.json').read_text())['rows'][0]
            self.assertEqual(row['email_date'], '2026-09-04')
            self.assertEqual(row['classification'], 'unmatched')
            self.assertEqual(row['source_availability'], 'unknown')
            self.assertFalse(profile['approved_for_experiment'])
            self.assertEqual(profile['proposed_retained_match_item_ids'], [])
            self.assertNotIn('not_relevant', json.dumps(profile))

    def test_private_output_guard_and_explicit_review(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            reviewed, db = root / 'reviewed.json', root / 'profile.sqlite'
            reviewed.write_text(json.dumps({'version':'v1', 'confirmed':False,
                                             'approved_for_experiment':True}))
            with self.assertRaises(ValueError):
                import_reviewed_profile(reviewed, db)
            self.assertFalse(db.exists())
            reviewed.write_text(json.dumps({'version':'v1', 'confirmed':True,
                                             'approved_for_experiment':True}))
            import_reviewed_profile(reviewed, db)
            self.assertTrue(db.exists())
            with self.assertRaises(ValueError):
                import_retrospective(root, root, REPOSITORY / 'private-email-output')

    def test_reviewed_audit_requires_bound_content_and_valid_indices(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            emails, public, output = (root / part for part in ('emails','public','output'))
            emails.mkdir(); public.mkdir()
            name = 'headlines.eml'
            email_file(emails / name, 'Thu, 03 Sep 2026 23:45:46 +0000',
                       'Company A new product.\n\nCompany B earnings.')
            (public / 'memo-2026-09-04.md').write_text('- Company A new product.\n')
            audit = root / 'audit.json'
            rows = [
                dict(date='2026-09-04',email_file=name,email_item=1,story_label='Company A new product',
                     status='Same',site_item=1,note='Same story'),
                dict(date='2026-09-04',email_file=name,email_item=2,story_label='Company B earnings',
                     status='Missing',site_item=None,note='Not in memo'),
            ]
            audit.write_text(json.dumps(rows))
            manifest = root / 'manifest.json'
            write_snapshot_manifest(emails, public, audit, manifest)
            result = import_reviewed_audit(emails, public, audit, manifest, output)
            self.assertEqual(result['counts'], {'Same':1,'Partial':0,'Missing':1,'Unpaired':0})
            self.assertFalse(result['approved_for_experiment'])
            self.assertEqual(result['rows'][0]['actual_feedback'], 'unknown')
            rows[0]['email_item'] = 9
            audit.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                import_reviewed_audit(emails, public, audit, manifest, output)
            rows[0]['email_item'] = 1
            rows[0]['story_label'] = 'Completely unrelated headline'
            audit.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'does not identify email paragraph'):
                import_reviewed_audit(emails, public, audit, manifest, output)
            rows[0]['story_label'] = 'Company A new product'
            audit.write_text(json.dumps(rows))
            (emails / name).write_bytes((emails / name).read_bytes().replace(b'new product', b'new service'))
            with self.assertRaises(ValueError):
                import_reviewed_audit(emails, public, audit, manifest, output)

    def test_reviewed_audit_rejects_stale_site_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); emails=root/'emails';public=root/'public';emails.mkdir();public.mkdir()
            email_file(emails/'note.eml','Thu, 03 Sep 2026 23:45:46 +0000','Company A news.')
            memo=public/'memo-2026-09-04.md';memo.write_text('- Company A news.\n')
            audit=root/'audit.json';audit.write_text(json.dumps([dict(date='2026-09-04',email_file='note.eml',
                         email_item=1,story_label='Company A news',status='Same',site_item=1)]))
            manifest=root/'manifest.json';write_snapshot_manifest(emails,public,audit,manifest)
            memo.write_text('- Company A revised news.\n')
            with self.assertRaisesRegex(ValueError,'content-hash manifest'):
                import_reviewed_audit(emails,public,audit,manifest,root/'output')


if __name__ == '__main__':
    unittest.main()
