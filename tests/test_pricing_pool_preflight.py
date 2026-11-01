import json
from pathlib import Path

import pytest

from pricing_pool_preflight import persist


def test_progress_save_survives_transient_windows_file_lock(tmp_path, monkeypatch):
    from pricing_pool_preflight import time

    target = tmp_path / "progress.json"
    target.write_text('{"old": true}')
    original = Path.replace
    attempts = []

    def temporarily_locked(source, destination):
        attempts.append(destination)
        if len(attempts) <= 2:
            raise PermissionError("Windows sharing violation")
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", temporarily_locked)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    persist(target, {"complete": True})
    assert len(attempts) == 3
    assert json.loads(target.read_text()) == {"complete": True}


def test_permanent_save_failure_preserves_old_and_complete_temporary_files(tmp_path, monkeypatch):
    from pricing_pool_preflight import time

    target = tmp_path / "progress.json"
    target.write_text('{"old": true}')

    def locked(*args):
        raise PermissionError("Persistent lock")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        persist(target, {"complete": True})
    assert json.loads(target.read_text()) == {"old": True}
    assert json.loads(target.with_suffix(".tmp").read_text()) == {"complete": True}
