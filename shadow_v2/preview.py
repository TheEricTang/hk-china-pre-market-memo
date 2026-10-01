"""Loopback-only reviewer preview. Never serves the private database or emails."""
import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .paths import REPOSITORY, private_path, private_directory
from .store import Store
from .models import parse_edition


def handler_for(store_path, origin):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log credentials, query strings or feedback bodies.

        def reply(self, status, value, content_type='application/json'):
            payload = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(payload)

        def safe_origin(self):
            return self.headers.get('Host') == urlparse(origin).netloc and self.headers.get('Origin', origin) == origin

        def api(self, event=None):
            if not self.safe_origin():
                return self.reply(403, {'error': 'Forbidden'})
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            with Store(store_path) as store:
                reviewer = store.authenticate(token)
                if not reviewer:
                    return self.reply(401, {'error': 'Unauthorized'})
                if event is None:
                    edition = store.latest_edition()
                    labels = store.get_item_feedback([i['id'] for i in edition['items']], reviewer=reviewer) if edition else {}
                    return self.reply(200, dict(edition=edition, labels=labels))
                if event.get('action') != 'feedback':
                    return self.reply(400, {'error': 'Invalid request'})
                try:
                    result = store.add_feedback(reviewer, event['item_id'], event['label'], event['client_event_id'], event['edition_id'])
                except (KeyError, ValueError, TypeError):
                    return self.reply(400, {'error': 'Invalid feedback'})
                return self.reply(200, result)

        def do_GET(self):
            if not self.safe_origin():
                return self.reply(403, {'error': 'Forbidden'})
            path = urlparse(self.path).path
            if path == '/api':
                if parse_qs(urlparse(self.path).query).get('action') != ['edition']:
                    return self.reply(400, {'error': 'Invalid request'})
                return self.api()
            if path == '/config.json':
                return self.reply(200, dict(apiBase='/api', publicStatus='/public/status.json', publicMemoBase=origin+'/public/memos/'))
            public_files = {'/':'index.html','/index.html':'index.html','/reviewer.js':'reviewer.js','/core.mjs':'core.mjs','/reviewer.css':'reviewer.css'}
            if path in public_files:
                file = REPOSITORY / 'docs/v2' / public_files[path]
            elif path == '/public/status.json':
                file = REPOSITORY / 'docs/status.json'
            elif re.fullmatch(r'/public/memos/memo-\d{4}-\d{2}-\d{2}\.md', path):
                file = REPOSITORY / 'memos' / path.rsplit('/', 1)[1]
            else:
                return self.reply(404, {'error': 'Not found'})
            if not file.is_file():
                return self.reply(404, {'error': 'Not found'})
            mime = 'text/javascript' if file.suffix in {'.js','.mjs'} else mimetypes.guess_type(file.name)[0] or 'text/plain'
            self.reply(200, file.read_bytes(), mime+'; charset=utf-8')

        def do_POST(self):
            if urlparse(self.path).path != '/api' or not self.safe_origin():
                return self.reply(403, {'error': 'Forbidden'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError()
                event = json.loads(self.rfile.read(size))
                if not isinstance(event, dict):
                    raise ValueError()
            except (ValueError, json.JSONDecodeError):
                return self.reply(400, {'error': 'Invalid request'})
            self.api(event)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    directory = private_directory(args.private_dir)
    store_path = private_path(directory/'memo-v2.db')
    origin = f'http://127.0.0.1:{args.port}'
    with Store(str(store_path)) as store:
        for memo in sorted((REPOSITORY/'memos').glob('memo-????-??-??.md')):
            store.register_edition(parse_edition(memo.read_text(), memo.stem[5:]))
        token = store.create_reviewer_token('local-reviewer')
        link = directory/'reviewer-link.txt'
        link.write_text(origin+'/#review='+token+'\n')
        link.chmod(0o600)
    print(f'Read-only preview: {origin}', flush=True)
    print(f'Private reviewer link saved locally: {link}', flush=True)
    try:
        HTTPServer(('127.0.0.1', args.port), handler_for(str(store_path), origin)).serve_forever()
    finally:
        with Store(str(store_path)) as store:
            store.revoke_token(token)


if __name__ == '__main__':
    main()
