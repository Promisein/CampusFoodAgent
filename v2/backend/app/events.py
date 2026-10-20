"""Local demo feedback, deliberately separate from historical training data.

Demo identities and opaque exposure IDs are not production authentication.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


EVENT_TYPES = ('impression', 'click', 'favorite', 'dislike', 'rating')


class EventPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    event_id: str = Field(min_length=1, max_length=128, pattern=r'\S')
    request_id: str = Field(min_length=1, max_length=128, pattern=r'\S')
    user_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r'\S')
    business_id: str = Field(min_length=1, max_length=128, pattern=r'\S')
    event_type: Literal['impression', 'click', 'favorite', 'dislike', 'rating']
    rating: StrictInt | None = Field(default=None, ge=1, le=5)

    @model_validator(mode='after')
    def validate_rating(self):
        if (self.event_type == 'rating') != (self.rating is not None):
            raise ValueError('rating is required only for rating events')
        return self


class EventConflict(ValueError):
    pass


class ExposureNotFound(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mapping(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else dict(value)


class EventRepository:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS exposures (
                    request_id TEXT PRIMARY KEY, user_id TEXT, query TEXT NOT NULL,
                    created_at TEXT NOT NULL, results_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                    user_id TEXT, business_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    rating INTEGER, created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES exposures(request_id));
                CREATE INDEX IF NOT EXISTS events_user ON events(user_id, created_at);
            ''')

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(str(self.db_path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def record_exposure(self, request, response):
        request, response = _mapping(request), _mapping(response)
        request_id = str(uuid4())
        with self._connection() as db:
            db.execute('INSERT INTO exposures VALUES (?, ?, ?, ?, ?)', (
                request_id, request.get('user_id'), request.get('query', ''), _now(),
                json.dumps(response.get('recommendations', []), ensure_ascii=False)))
        return request_id

    def record_event(self, payload):
        payload = EventPayload.model_validate(_mapping(payload)).model_dump()
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self._connection() as db:
            # Serialize check+insert across repository instances and processes.
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM events WHERE event_id=?', (payload['event_id'],)).fetchone()
            if existing:
                if existing['payload_json'] != encoded:
                    raise EventConflict('event_id already belongs to a different payload')
                return self._event(existing)
            exposure = db.execute('SELECT * FROM exposures WHERE request_id=?', (payload['request_id'],)).fetchone()
            if exposure is None or exposure['user_id'] != payload['user_id']:
                raise ExposureNotFound('Matching demo exposure not found')
            if payload['business_id'] not in {r['business_id'] for r in json.loads(exposure['results_json'])}:
                raise ExposureNotFound('Business was not included in this exposure')
            created_at = _now()
            db.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (
                payload['event_id'], payload['request_id'], payload['user_id'], payload['business_id'],
                payload['event_type'], payload['rating'], created_at, encoded))
            return {**payload, 'created_at': created_at}

    @staticmethod
    def _event(row):
        return {**json.loads(row['payload_json']), 'created_at': row['created_at']}

    def history(self, user_id, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('limit must be an integer from 1 to 1000')
        with self._connection() as db:
            return [self._event(row) for row in db.execute(
                'SELECT * FROM events WHERE user_id IS ? ORDER BY rowid DESC LIMIT ?', (user_id, limit))]

    def favorites(self, user_id):
        with self._connection() as db:
            rows = db.execute('''SELECT e.*, x.results_json FROM events e
                JOIN exposures x ON x.request_id=e.request_id
                WHERE e.user_id IS ? AND e.event_type='favorite'
                AND NOT EXISTS (SELECT 1 FROM events newer
                    WHERE newer.user_id IS e.user_id AND newer.business_id=e.business_id
                    AND newer.event_type IN ('favorite','dislike') AND newer.rowid>e.rowid)
                ORDER BY e.rowid DESC''', (user_id,)).fetchall()
            return [{**next(item for item in json.loads(row['results_json'])
                             if item['business_id'] == row['business_id']),
                     'favorited_at': row['created_at'], 'request_id': row['request_id']} for row in rows]

    def metrics(self):
        with self._connection() as db:
            db.execute('BEGIN')
            counts = {kind: 0 for kind in EVENT_TYPES}
            counts.update({row[0]: row[1] for row in db.execute('SELECT event_type,COUNT(*) FROM events GROUP BY event_type')})
            exposures = db.execute('SELECT results_json FROM exposures').fetchall()
            unique = db.execute('''SELECT COUNT(*) AS impressed,
                COALESCE(SUM(has_click),0) AS clicked FROM (
                    SELECT request_id,business_id,
                    MAX(CASE WHEN event_type='click' THEN 1 ELSE 0 END) AS has_click
                    FROM events GROUP BY request_id,business_id
                    HAVING MAX(CASE WHEN event_type='impression' THEN 1 ELSE 0 END)=1
                )''').fetchone()
        return {'scope': 'local_demo_descriptive', 'event_counts': counts,
                'exposure_requests': len(exposures),
                'exposed_items': sum(len(json.loads(row[0])) for row in exposures),
                'ctr': counts['click'] / counts['impression'] if counts['impression'] else None,
                'ctr_numerator': 'click_events', 'ctr_denominator': 'impression_events',
                'impressed_exposure_items': unique['impressed'],
                'clicked_impressed_exposure_items': unique['clicked'],
                'bounded_unique_ctr': unique['clicked'] / unique['impressed'] if unique['impressed'] else None,
                'bounded_unique_ctr_denominator': 'distinct (request_id,business_id) with impression',
                'bounded_unique_ctr_note': 'Numerator counts those impressed items with any click. Clicks without an impression are excluded. Repeat event IDs or repeated actions never inflate this rate.',
                'note': 'Idempotent event counts, not unique-user CTR; repeated actions can exceed 1. Local demo identities have no authentication.'}


def register_event_routes(app, repository_provider):
    @app.post('/api/v2/events')
    def record_event(payload: EventPayload):
        try:
            return repository_provider().record_event(payload)
        except EventConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ExposureNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail='Local event store unavailable') from exc

    @app.get('/api/v2/users/{user_id}/favorites')
    def favorites(user_id: str):
        try:
            return {'user_id': user_id, 'scope': 'local_demo_no_auth', 'favorites': repository_provider().favorites(user_id)}
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail='Local event store unavailable') from exc

    @app.get('/api/v2/users/{user_id}/history')
    def history(user_id: str, limit: int = Query(default=100, ge=1, le=1000)):
        try:
            return {'user_id': user_id, 'scope': 'local_demo_no_auth', 'events': repository_provider().history(user_id, limit)}
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail='Local event store unavailable') from exc

    @app.get('/api/v2/events/metrics')
    def metrics():
        try:
            return repository_provider().metrics()
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail='Local event store unavailable') from exc
