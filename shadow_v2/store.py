"""Private SQLite development backend. Labels are explicit and events immutable."""
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
import uuid
from datetime import date
from .models import digest, normalize


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if path != ':memory:':
            os.chmod(path, 0o600)
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS editions(id TEXT PRIMARY KEY, day TEXT NOT NULL, payload TEXT NOT NULL, seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS membership(edition_id TEXT REFERENCES editions(id), item_id TEXT REFERENCES items(id), PRIMARY KEY(edition_id,item_id));
        CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, reviewer TEXT NOT NULL, role TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, reviewer TEXT NOT NULL, edition_id TEXT NOT NULL, item_id TEXT NOT NULL, label TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS selections(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, reviewer TEXT NOT NULL, edition_id TEXT NOT NULL REFERENCES editions(id), selected_item_ids TEXT NOT NULL, created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS selections_latest ON selections(reviewer,edition_id,seq DESC);
        CREATE INDEX IF NOT EXISTS selections_rate ON selections(reviewer,created);
        CREATE TABLE IF NOT EXISTS profiles(version TEXT PRIMARY KEY, payload TEXT NOT NULL, seq INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS embeddings(item_id TEXT REFERENCES items(id), model TEXT, version TEXT, body_hash TEXT, vector TEXT, PRIMARY KEY(item_id,model,version));
        ''')

    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def register_edition(self, edition):
        with self.db:
            previous = self.db.execute('SELECT payload FROM editions WHERE id=?', (edition['id'],)).fetchone()
            if previous and json.loads(previous[0]) != edition: raise ValueError('immutable edition conflict')
            self.db.execute('INSERT OR IGNORE INTO editions VALUES(?,?,?,?)', (edition['id'], edition['edition_date'], json.dumps(edition), time.time_ns()))
            for item in edition['items']:
                old = self.get_item(item['id'])
                if old is not None and old != item:
                    # Position can change between editions; content identities cannot.
                    if normalize(old['body']) != normalize(item['body']) or any(old.get(k) != item.get(k) for k in ('content_hash', 'edition_date')):
                        raise ValueError('immutable item conflict')
                self.db.execute('INSERT OR IGNORE INTO items VALUES(?,?)', (item['id'], json.dumps(item)))
                self.db.execute('INSERT OR IGNORE INTO membership VALUES(?,?)', (edition['id'], item['id']))

    def latest_edition(self):
        row = self.db.execute('SELECT payload FROM editions ORDER BY day DESC,seq DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def get_item(self, item_id):
        row = self.db.execute('SELECT payload FROM items WHERE id=?', (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def create_reviewer_token(self, reviewer: str, role: str = 'reviewer') -> str:
        if role not in ('reviewer', 'ci') or not reviewer: raise ValueError('invalid principal')
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute('INSERT INTO tokens(hash,reviewer,role) VALUES(?,?,?)', (digest(token), reviewer, role))
        return token

    def authenticate(self, token: str, role: str = 'reviewer'):
        hashed = digest(token)
        row = self.db.execute('SELECT * FROM tokens WHERE hash=?', (hashed,)).fetchone()
        if row and hmac.compare_digest(row['hash'], hashed) and not row['revoked'] and row['role'] == role:
            return row['reviewer']
        return None

    def revoke_token(self, token: str):
        with self.db: self.db.execute('UPDATE tokens SET revoked=1 WHERE hash=?', (digest(token),))

    def rotate_token(self, token: str) -> str:
        row = self.db.execute('SELECT * FROM tokens WHERE hash=? AND revoked=0', (digest(token),)).fetchone()
        if not row: raise ValueError('invalid token')
        self.revoke_token(token)
        return self.create_reviewer_token(row['reviewer'], row['role'])

    def add_feedback(self, reviewer: str, item_id: str, label: str, client_event_id: str, edition_id: str):
        if label not in ('used', 'not_relevant', 'cleared'): raise ValueError('invalid label')
        uuid.UUID(client_event_id)
        if not reviewer: raise ValueError('reviewer required')
        with self.db:
            # Transaction serializes deduplication, limits, and append ordering across workers.
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM selections WHERE event_id=?', (client_event_id,)).fetchone(): raise ValueError('event id conflict')
            existing = self.db.execute('SELECT * FROM events WHERE event_id=?', (client_event_id,)).fetchone()
            if existing:
                if any(existing[k] != v for k,v in dict(reviewer=reviewer,item_id=item_id,label=label,edition_id=edition_id).items()):
                    raise ValueError('event id conflict')
            else:
                if not self.db.execute('SELECT 1 FROM membership WHERE edition_id=? AND item_id=?', (edition_id,item_id)).fetchone():
                    raise ValueError('edition mismatch')
                if self._recent_event_count(reviewer) >= 60:
                    raise ValueError('rate limit')
                self.db.execute('INSERT INTO events(event_id,reviewer,edition_id,item_id,label,created) VALUES(?,?,?,?,?,?)', (client_event_id,reviewer,edition_id,item_id,label,time.time()))
        return dict(saved=True, client_event_id=client_event_id, label=label)

    def _recent_event_count(self, reviewer):
        cutoff = time.time()-60
        return sum(self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE reviewer=? AND created>?', (reviewer,cutoff)).fetchone()[0] for table in ('events','selections'))

    def add_selection(self, reviewer, edition_id, selected_item_ids, client_event_id):
        if not reviewer or not isinstance(edition_id,str) or not edition_id: raise ValueError('invalid principal or edition')
        uuid.UUID(client_event_id)
        if not isinstance(selected_item_ids,list) or len(selected_item_ids)>100 or any(not isinstance(item,str) or not item for item in selected_item_ids):
            raise ValueError('invalid selection')
        if len(set(selected_item_ids)) != len(selected_item_ids): raise ValueError('duplicate selected item')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM events WHERE event_id=?',(client_event_id,)).fetchone(): raise ValueError('event id conflict')
            existing = self.db.execute('SELECT * FROM selections WHERE event_id=?',(client_event_id,)).fetchone()
            if existing:
                if existing['reviewer'] != reviewer or existing['edition_id'] != edition_id or json.loads(existing['selected_item_ids']) != selected_item_ids:
                    raise ValueError('event id conflict')
            else:
                if not self.db.execute('SELECT 1 FROM editions WHERE id=?',(edition_id,)).fetchone(): raise ValueError('unknown edition')
                for item_id in selected_item_ids:
                    if not self.db.execute('SELECT 1 FROM membership WHERE edition_id=? AND item_id=?',(edition_id,item_id)).fetchone():
                        raise ValueError('edition mismatch')
                if self._recent_event_count(reviewer) >= 60: raise ValueError('rate limit')
                self.db.execute('INSERT INTO selections(event_id,reviewer,edition_id,selected_item_ids,created) VALUES(?,?,?,?,?)',
                                (client_event_id,reviewer,edition_id,json.dumps(selected_item_ids),time.time()))
        return dict(saved=True,client_event_id=client_event_id,selected_item_ids=list(selected_item_ids))

    def get_selection_items(self, edition_id, reviewer):
        row = self.db.execute('SELECT selected_item_ids FROM selections WHERE edition_id=? AND reviewer=? ORDER BY seq DESC LIMIT 1',(edition_id,reviewer)).fetchone()
        return json.loads(row[0]) if row else []

    def get_selection_signals(self, item_ids, reviewer=None):
        # Absence only means no current weak-positive evidence. It is never a negative label.
        result = {item_id:dict(selected=False,position=None,selection_count=0) for item_id in item_ids}
        query = 'SELECT * FROM selections WHERE seq IN (SELECT MAX(s.seq) FROM selections s JOIN editions e ON e.id=s.edition_id'
        args = []
        if reviewer is not None: query += ' WHERE s.reviewer=?'; args.append(reviewer)
        query += ' GROUP BY s.reviewer,e.day) ORDER BY seq'
        for row in self.db.execute(query,args):
            for position,item_id in enumerate(json.loads(row['selected_item_ids'])):
                if item_id in result:
                    signal = result[item_id]
                    signal.update(selected=True,position=position,selection_count=signal['selection_count']+1)
        return result

    def get_item_feedback(self, item_ids, reviewer=None):
        result = {}
        for item_id in item_ids:
            query = 'SELECT label FROM events WHERE item_id=?'
            args = [item_id]
            if reviewer is not None: query += ' AND reviewer=?'; args.append(reviewer)
            row = self.db.execute(query+' ORDER BY seq DESC LIMIT 1', args).fetchone()
            result[item_id] = row[0] if row and row[0] != 'cleared' else 'unlabeled'
        return result

    def get_preference_profile(self, version='latest'):
        row = self.db.execute('SELECT payload FROM profiles ORDER BY seq DESC LIMIT 1' if version == 'latest' else 'SELECT payload FROM profiles WHERE version=?', () if version == 'latest' else (version,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_preference_profile(self, profile):
        profile = dict(profile)
        profile.setdefault('approved_for_experiment', False)
        with self.db: self.db.execute('INSERT INTO profiles VALUES(?,?,?)', (profile['version'], json.dumps(profile), time.time_ns()))

    def save_shadow_run(self, run):
        with self.db: self.db.execute('INSERT OR REPLACE INTO runs VALUES(?,?)', (run.get('id',run.get('run_id',str(uuid.uuid4()))),json.dumps(run)))

    def add_embedding(self, item_id, vector, model, version):
        item = self.get_item(item_id)
        if not item: raise ValueError('unknown item')
        vector = self._vector(vector)
        with self.db: self.db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?)', (item_id,model,version,digest(normalize(item['body'])),json.dumps(vector)))

    @staticmethod
    def _vector(vector):
        if not vector or len(vector)>4096 or any(not isinstance(x,(int,float)) or isinstance(x,bool) or abs(x)>1e20 or not math.isfinite(x) for x in vector) or math.sqrt(sum(x*x for x in vector)) < 1e-20:
            raise ValueError('invalid vector')
        norm = math.sqrt(sum(x*x for x in vector))
        return [x/norm for x in vector]

    def has_embedding(self, item_id, model, version):
        item = self.get_item(item_id)
        if not item: return False
        row = self.db.execute('SELECT body_hash FROM embeddings WHERE item_id=? AND model=? AND version=?', (item_id,model,version)).fetchone()
        return bool(row and row['body_hash'] == digest(normalize(item['body'])))

    def search_history(self, vector, model, version, date_from=None, date_to=None, tickers=None, topics=None, limit=10):
        vector = self._vector(vector)
        if date_from: date.fromisoformat(date_from)
        if date_to: date.fromisoformat(date_to)
        if date_from and date_to and date_from > date_to: raise ValueError('invalid date range')
        limit = max(1,min(int(limit),50))
        query = '''SELECT e.vector,e.body_hash,i.payload FROM embeddings e JOIN items i ON i.id=e.item_id WHERE e.model=? AND e.version=?'''
        candidates = []
        # Date filter applies before the 5000-entry safety bound.
        args = [model, version]
        if date_from: query += " AND json_extract(i.payload,'$.edition_date')>=?"; args.append(date_from)
        if date_to: query += " AND json_extract(i.payload,'$.edition_date')<=?"; args.append(date_to)
        for row in self.db.execute(query+" ORDER BY json_extract(i.payload,'$.edition_date') DESC LIMIT 5000", args):
            item = json.loads(row['payload'])
            try: other = self._vector(json.loads(row['vector']))
            except ValueError: continue
            if row['body_hash'] != digest(normalize(item['body'])) or len(vector)!=len(other): continue
            if tickers and not set(tickers).intersection(item['tickers']): continue
            if topics and not set(topics).intersection(item['topics']): continue
            similarity = sum(a*b for a,b in zip(vector,other))/(math.sqrt(sum(a*a for a in vector))*math.sqrt(sum(b*b for b in other)))
            age = max(0,(date.today()-date.fromisoformat(item['edition_date'])).days)
            candidates.append(dict(item, similarity=similarity,recency_score=1/(1+age/30),history_only=True,label=self.get_item_feedback([item['id']])[item['id']]))
        for candidate in candidates:
            candidate['retrieval_score'] = 0.9 * candidate['similarity'] + 0.1 * candidate['recency_score']
        return sorted(candidates,key=lambda x:x['retrieval_score'],reverse=True)[:limit]
