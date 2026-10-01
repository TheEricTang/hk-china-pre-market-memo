import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from shadow_v2.models import parse_edition
from shadow_v2.preview import handler_for
from shadow_v2.store import Store
from shadow_v2.paths import private_path, REPOSITORY


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'db.sqlite')
        self.edition=parse_edition('Morning memo\nResearch cutoff\n\n- **Test:** Statement. [[Source](https://example.com/news)]', '2026-10-01')
        with Store(self.path) as store:
            store.register_edition(self.edition)
            self.token=store.create_reviewer_token('test')
        self.server=HTTPServer(('127.0.0.1',0),handler_for(self.path,'http://127.0.0.1:0'))
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.server.RequestHandlerClass=handler_for(self.path,self.origin)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,path,token=None,body=None,headers=None):
        req=Request(self.origin+path,data=json.dumps(body).encode() if body else None,headers={**({'Authorization':'Bearer '+token} if token else {}),**({'Content-Type':'application/json'} if body else {}),**(headers or {})})
        with urlopen(req) as r:return json.loads(r.read())

    def test_auth_undo_idempotency_and_revocation(self):
        with self.assertRaises(HTTPError) as error:self.request('/api?action=edition')
        self.assertEqual(error.exception.code,401)
        payload=self.request('/api?action=edition',self.token)
        item=self.edition['items'][0]['id']
        self.assertEqual(payload['labels'][item],'unlabeled')
        event=dict(action='feedback',item_id=item,edition_id=self.edition['id'],label='used',client_event_id=str(uuid4()))
        self.assertTrue(self.request('/api',self.token,event)['saved'])
        self.assertTrue(self.request('/api',self.token,event)['saved'])
        self.assertEqual(self.request('/api?action=edition',self.token)['labels'][item],'used')
        self.request('/api',self.token,dict(event,label='cleared',client_event_id=str(uuid4())))
        self.assertEqual(self.request('/api?action=edition',self.token)['labels'][item],'unlabeled')
        with Store(self.path) as store:store.revoke_token(self.token)
        with self.assertRaises(HTTPError):self.request('/api?action=edition',self.token)

    def test_origin_host_and_path_isolation(self):
        for path,headers in [('/api?action=edition',{'Origin':'https://evil.example'}),('/api?action=edition',{'Host':'evil.example'}),('/../db.sqlite',{}),('/public/../../db.sqlite',{})]:
            with self.assertRaises(HTTPError):self.request(path,self.token,headers=headers)
        with self.assertRaises(ValueError):private_path(REPOSITORY/'memos/private.db')
        with self.assertRaises(ValueError):private_path(REPOSITORY/'docs/v2/../../docs/key')

    def test_wrong_edition_and_admin_action_rejected(self):
        event=dict(action='feedback',item_id=self.edition['items'][0]['id'],edition_id='other',label='used',client_event_id=str(uuid4()))
        with self.assertRaises(HTTPError):self.request('/api',self.token,event)
        with self.assertRaises(HTTPError):self.request('/api',self.token,{'action':'register_edition'})


if __name__=='__main__':unittest.main()
