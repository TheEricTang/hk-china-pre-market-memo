"""Private CI adapter: only a scoped CI token is sent to the dedicated Edge API."""
import json
import urllib.request
from urllib.parse import urlparse


class SupabaseStore:
    def __init__(self, endpoint, token):
        url = urlparse(endpoint)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('dedicated HTTPS Edge endpoint required')
        if not token: raise ValueError('scoped CI token required')
        self.endpoint, self._token = endpoint, token

    def _call(self, operation, **arguments):
        request = urllib.request.Request(self.endpoint,data=json.dumps(dict(action='ci',operation=operation,arguments=arguments)).encode(),headers={'Authorization':'Bearer '+self._token,'Content-Type':'application/json'},method='POST')
        try:
            # Redirects are forbidden: never forward credentials to another endpoint.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs): return None
            with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
                return json.load(response)['result']
        except Exception:
            raise RuntimeError('private backend request failed') from None

    def register_edition(self,edition): return self._call('register_edition',edition=edition)
    def latest_edition(self): return self._call('latest_edition')
    def get_item(self,item_id): return self._call('get_item',item_id=item_id)
    def get_item_feedback(self,item_ids): return self._call('get_item_feedback',item_ids=item_ids)
    def get_preference_profile(self,version='latest'): return self._call('get_preference_profile',version=version)
    def save_preference_profile(self,profile): return self._call('save_preference_profile',profile=profile)
    def save_shadow_run(self,run): return self._call('save_shadow_run',run=run)
    def has_embedding(self,item_id,model,version): return self._call('has_embedding',item_id=item_id,model=model,version=version)
    def add_embedding(self,item_id,vector,model,version): return self._call('add_embedding',item_id=item_id,vector=vector,model=model,version=version)
    def search_history(self,vector,model,version,date_from=None,date_to=None,tickers=None,topics=None,limit=10):
        return self._call('search_history',vector=vector,model=model,version=version,date_from=date_from,date_to=date_to,tickers=tickers,topics=topics,limit=limit)
