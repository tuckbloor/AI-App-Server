"""Execute the requested file afresh for each UI event, with isolated per-session state."""
from pathlib import Path
import runpy
from .ui import Context, set_context, reset_context


def render(script: Path, values: dict | None = None, *, session: dict | None = None) -> list[dict]:
    if not script.is_file(): raise FileNotFoundError(f'Application not found: {script}')
    context = Context(values=values or {}, session=session if session is not None else {})
    token = set_context(context)
    try:
        # Explicit script execution, requested by the local developer. Never use on untrusted source.
        runpy.run_path(str(script), run_name='__main__')
        return context.components
    finally:
        reset_context(token)
