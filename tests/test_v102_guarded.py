"""New invariants for the guarded upgrade and production acceptance."""
import importlib.util
from pathlib import Path
import pytest
from ai_app_server.desktop_launcher import pick_port
from ai_app_server.hosting import save_hosting, read_hosting


def test_existing_configured_port_must_not_move(tmp_path, monkeypatch):
    home=tmp_path/'project'
    (home/'app').mkdir(parents=True)
    script=home/'app/app.py'
    script.write_text('print("hi")')
    data=home/'data'
    save_hosting(data, 8501)
    monkeypatch.setattr('ai_app_server.desktop_launcher.instance_responding',lambda *args:False)
    monkeypatch.setattr('ai_app_server.desktop_launcher.is_port_free',lambda *args:False)
    with pytest.raises(RuntimeError,match='Configured port 8501 is busy'):
        pick_port(script,data)
    assert read_hosting(data)['port']==8501


def test_production_acceptance_config(tmp_path, monkeypatch):
    import sys
    root=Path(__file__).resolve().parents[1]
    location=root/'production/production_acceptance.py'
    spec=importlib.util.spec_from_file_location('acceptance',location)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    compose=root/'production/compose.yaml'
    good={'AI_APP_SERVER_PUBLIC_ORIGIN':'https://ai.example.com',
          'AI_APP_SERVER_BEHIND_TLS_PROXY':'1',
          'AI_APP_SERVER_APP_PASSWORD':'a-unique-production-secret-long-123'}
    assert all(ok for _,ok in mod.validate(good,compose))
    good['AI_APP_SERVER_PUBLIC_ORIGIN']='http://localhost'
    assert not all(ok for _,ok in mod.validate(good,compose))
