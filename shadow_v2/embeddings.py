"""Explicit, versioned OpenAI embedding calls; archive ingestion never calls this."""
import os
from .store import Store


class OpenAIEmbeddingAdapter:
    def __init__(self, client=None, model='text-embedding-3-small', version='v1'):
        if model != 'text-embedding-3-small': raise ValueError('unsupported embedding model')
        if not version: raise ValueError('embedding version required')
        self.model, self.version = model, version
        if client is None:
            from openai import OpenAI
            key = os.environ.get('V2_OPENAI_API_KEY')
            if not key: raise ValueError('V2_OPENAI_API_KEY required')
            client = OpenAI(api_key=key, timeout=30, max_retries=1)
        self.client = client
        self.last_usage = {}

    def embed(self, text):
        if not text or len(text)>30000: raise ValueError('embedding text length outside bounds')
        response = self.client.embeddings.create(model=self.model,input=text,dimensions=1536)
        usage = getattr(response, 'usage', None)
        self.last_usage = {'input_tokens': getattr(usage, 'prompt_tokens', 0), 'total_tokens': getattr(usage, 'total_tokens', 0)}
        vector = response.data[0].embedding
        if len(vector)!=1536: raise ValueError('embedding dimension mismatch')
        return Store._vector(vector)
