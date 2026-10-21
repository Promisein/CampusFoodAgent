"""Bounded persistent local sessions; turn mutations serialize in SQLite.

The transaction spans tool execution for this single-worker demo. Separate event
writes are idempotent, not atomically committed with this database.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from app.agent.state import initial_state


class SessionError(ValueError):
    def __init__(self,status,reason):
        self.status,self.reason=status,reason
        super().__init__(reason)


class SessionRepository:
    def __init__(self,path,*,clock=time.time,ttl=86400,max_turns=30,max_sessions=1000):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock,self.ttl,self.max_turns,self.max_sessions=clock,ttl,max_turns,max_sessions
        with self.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, version INTEGER NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                turn_id TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL,
                PRIMARY KEY(session_id,turn_id));''')

    @contextmanager
    def connection(self):
        db=sqlite3.connect(str(self.path),timeout=1)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:yield db
        finally:db.close()

    def _load(self,db,session_id):
        row=db.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()
        if row is None:raise SessionError(404,'session_not_found')
        if row['expires'] <= self.clock():raise SessionError(410,'session_expired')
        return row

    def create(self,context):
        session_id=str(uuid4());expires=self.clock()+self.ttl
        state=initial_state(context)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM sessions WHERE expires<=?',(self.clock(),))
            if db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]>=self.max_sessions:
                raise SessionError(503,'session_capacity_reached')
            db.execute('INSERT INTO sessions VALUES (?,0,?,?)',(session_id,expires,json.dumps(state)))
        return {'session_id':session_id,'version':0,'expires_at':expires,'state':state,
                'limits':{'max_turns':self.max_turns,'ttl_seconds':self.ttl},'scope':'local_demo_no_auth'}

    def get(self,session_id):
        with self.connection() as db:row=self._load(db,session_id)
        return {'session_id':session_id,'version':row['version'],'expires_at':row['expires'],
                'state':json.loads(row['state']),'scope':'local_demo_no_auth'}

    def turn(self,session_id,payload,handler):
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=self._load(db,session_id)
            prior=db.execute('SELECT * FROM turns WHERE session_id=? AND turn_id=?',(session_id,payload['turn_id'])).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise SessionError(409,'turn_id_payload_conflict')
                return json.loads(prior['response'])
            if row['version']!=payload['expected_version']:raise SessionError(409,'stale_session_version')
            if row['version']>=self.max_turns:raise SessionError(409,'session_turn_limit')
            state=json.loads(row['state'])
            reply=handler(state)
            state['messages']=(state['messages']+[{'role':'user','text':payload.get('message','')[:1000]},
                {'role':'assistant','text':reply.get('message','')[:2000]}])[-20:]
            encoded=json.dumps(state,ensure_ascii=False)
            if len(encoded)>250000:raise SessionError(503,'session_state_budget')
            reply.update(session_id=session_id,version=row['version']+1,expires_at=row['expires'],
                state={'context':state['context'],'slots':state['slots'],'pending_clarification':state['pending_clarification']},
                scope='local_demo_no_auth')
            response=json.dumps(reply,ensure_ascii=False)
            if len(response)>250000:raise SessionError(503,'turn_response_budget')
            db.execute('UPDATE sessions SET version=?,state=? WHERE id=?',(row['version']+1,encoded,session_id))
            db.execute('INSERT INTO turns VALUES (?,?,?,?)',(session_id,payload['turn_id'],fingerprint,response))
            return reply
