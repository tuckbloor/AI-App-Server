"""Optional local Ollama integration. Models stay on the user's own machine."""
import json
import os
import time
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import urlsplit

_cache = {'at': 0.0, 'data': []}


def endpoint():
    base = os.getenv('AI_APP_SERVER_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    parsed = urlsplit(base)
    # Do not accept arbitrary addresses from browser widgets / untrusted projects.
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Invalid Ollama URL')
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Ollama URL must contain only a trusted origin')
    return base


def models(*, refresh=False):
    if not refresh and time.monotonic() - _cache['at'] < 12:
        return _cache['data'][:]
    try:
        with urlopen(endpoint() + '/api/tags', timeout=5) as res:
            body = json.load(res)
        names = sorted({m['name'] for m in body.get('models', []) if isinstance(m.get('name'), str)})
        _cache.update({'at': time.monotonic(), 'data': names})
        return names
    except (OSError, ValueError, KeyError, TypeError):
        _cache.update({'at': time.monotonic(), 'data': []})
        return []


def generate(prompt: str, model: str, *, timeout=300):
    # Explicit generation action only. Model must be one returned by Ollama.
    if not model or model not in models(refresh=True):
        raise ValueError('Choose an installed Ollama model')
    if not prompt.strip() or len(prompt) > 15000:
        raise ValueError('Enter a prompt (up to 15,000 characters)')
    body = json.dumps({'model': model, 'prompt': prompt, 'stream': False}).encode('utf-8')
    req = Request(endpoint() + '/api/generate', data=body, headers={'Content-Type':'application/json'}, method='POST')
    with urlopen(req, timeout=timeout) as res:
        return json.load(res).get('response', '')
