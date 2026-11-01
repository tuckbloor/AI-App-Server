"""Small declarative UI; each browser session has independent widget state."""
from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
import hashlib
import html
import inspect
import json

@dataclass
class Context:
    values: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    components: list[dict[str, Any]] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    container: str = 'main'

_current: ContextVar[Context | None] = ContextVar('ai_app_current', default=None)

def set_context(ctx: Context):
    return _current.set(ctx)

def reset_context(token):
    _current.reset(token)

def ctx() -> Context:
    value = _current.get()
    if value is None:
        raise RuntimeError('UI functions must be called inside an app started with ai-app-server run')
    return value


def session_state() -> dict[str, Any]:
    """Return state retained for the lifetime of this browser connection.

    Every browser connection has its own state; it is not shared between
    different users or stored in the server administrator database.
    """
    return ctx().session

def add(kind: str, **props):
    ctx().components.append({'type':kind, 'container':ctx().container, **props})

def key_for(label: str, key: str | None = None) -> str:
    if key is not None:
        return str(key)
    f = inspect.currentframe().f_back.f_back
    location = f'{f.f_code.co_filename}:{f.f_lineno}:{label}'
    index = ctx().counters.get(location, 0)
    ctx().counters[location] = index + 1
    return hashlib.sha256(f'{location}:{index}'.encode()).hexdigest()[:16]

def title(value): add('title', value=str(value))
def heading(value): add('heading', value=str(value))
def caption(value): add('caption', value=str(value))
def section(value): add('section', value=str(value))
def guide(value): add('guide', value=str(value))

def text(value): add('text', value=str(value))
def output(value): add('output', value=str(value))
def write(value): add('text', value=str(value))
def markdown(value): add('markdown', value=str(value))
def code(value, language='python'): add('code', value=str(value), language=str(language))
def success(value): add('notice', tone='success', value=str(value))
def warning(value): add('notice', tone='warning', value=str(value))
def error(value): add('notice', tone='error', value=str(value))
def divider(): add('divider')
def metric(label, value): add('metric', label=str(label), value=str(value))

def button(label: str, *, key: str | None = None) -> bool:
    ident = key_for(label, key)
    add('button', id=ident, label=str(label))
    return bool(ctx().values.get(ident, False))

def input(label: str, value: str = '', *, key: str | None = None) -> str:
    ident = key_for(label, key)
    result = str(ctx().values.get(ident, value))
    add('input', id=ident, label=str(label), value=result)
    return result

def text_area(label: str, value: str = '', *, key: str | None = None, height: int = 120) -> str:
    ident = key_for(label, key)
    result = str(ctx().values.get(ident, value))
    add('textarea', id=ident, label=str(label), value=result, height=max(80, min(height, 500)))
    return result


def ollama_model_select(label: str = 'Ollama model', *, key: str | None = None):
    from .ollama import models
    available = models()
    if not available:
        warning('Ollama is not connected or has no downloaded models. Start Ollama and run: ollama pull llama3.2')
        return None
    return selectbox(label, available, key=key)


def number_input(label: str, value: float = 0, *, key: str | None = None) -> float:
    ident = key_for(label, key)
    try: result = float(ctx().values.get(ident, value))
    except (ValueError, TypeError): result = float(value)
    add('number', id=ident, label=str(label), value=result)
    return result

def checkbox(label: str, value: bool = False, *, key: str | None = None) -> bool:
    ident = key_for(label, key)
    result = bool(ctx().values.get(ident, value))
    add('checkbox', id=ident, label=str(label), value=result)
    return result

def selectbox(label: str, options, *, key: str | None = None):
    opts = list(options)
    ident = key_for(label, key)
    result = ctx().values.get(ident, opts[0] if opts else None)
    if result not in opts: result = opts[0] if opts else None
    add('select', id=ident, label=str(label), options=opts, value=result)
    return result

def table(data):
    if hasattr(data, 'to_dict'):
        try: data = data.to_dict(orient='records')
        except TypeError: data = data.to_dict()
    if isinstance(data, dict): data = [data]
    if not isinstance(data, list): data = list(data)
    add('table', rows=json.loads(json.dumps(data, default=str)))

def dataframe(data): table(data)

class _Container:
    def __init__(self, name): self.name=name
    def __enter__(self):
        self.previous = ctx().container
        ctx().container = self.name
        return self
    def __exit__(self,*_): ctx().container = self.previous

def sidebar(): return _Container('sidebar')
def columns(n: int):
    # Simple grid slots; use with each block: with col[0]: ...
    if n < 1 or n > 6: raise ValueError('columns must be between 1 and 6')
    return [_Container(f'column-{i}-of-{n}') for i in range(n)]
