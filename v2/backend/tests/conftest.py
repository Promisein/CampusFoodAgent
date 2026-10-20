"""Keep automated API exposures out of the interactive demo's event database."""
import pytest


@pytest.fixture(autouse=True)
def isolated_default_event_store(tmp_path,monkeypatch):
    import app.main as main
    from app.events import EventRepository
    repository=EventRepository(tmp_path/'api_events.sqlite3')
    monkeypatch.setattr(main,'get_event_repository',lambda:repository)
