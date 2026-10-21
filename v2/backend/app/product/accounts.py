"""Small single-host account store; public product routes never trust client user IDs."""
from contextlib import contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4


PASSWORD_ROUNDS=310_000
SESSION_SECONDS=7*86400
HANDLE_PATTERN=re.compile(r'[a-z0-9_-]{3,32}\Z')


class AccountError(ValueError):
    def __init__(self,status,code):
        self.status,self.code=status,code
        super().__init__(code)


class AccountStore:
    def __init__(self,path,*,clock=time.time):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,handle TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,password_hash TEXT NOT NULL,created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS account_sessions (
                    token_hash TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    expires_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS account_sessions_owner ON account_sessions(account_id,expires_at);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    handle TEXT PRIMARY KEY,failures INTEGER NOT NULL,
                    window_start REAL NOT NULL,blocked_until REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS product_conversations (
                    session_id TEXT PRIMARY KEY,account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS product_conversations_owner ON product_conversations(account_id,updated_at);
            ''')

    @contextmanager
    def connection(self):
        db=sqlite3.connect(str(self.path),timeout=5)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def _handle(value):
        handle=value.strip().lower() if isinstance(value,str) else ''
        if not HANDLE_PATTERN.fullmatch(handle):raise AccountError(422,'invalid_handle')
        return handle

    @staticmethod
    def _password(value):
        if not isinstance(value,str) or not 12<=len(value)<=128:
            raise AccountError(422,'invalid_password_length')
        return value.encode('utf-8')

    @staticmethod
    def _hash_password(password,salt):
        return hashlib.pbkdf2_hmac('sha256',password,salt,PASSWORD_ROUNDS).hex()

    @staticmethod
    def _public(row):return {'id':row['id'],'handle':row['handle']}

    def register(self,handle,password):
        handle=self._handle(handle)
        password=self._password(password)
        salt=secrets.token_bytes(24)
        digest=self._hash_password(password,salt)
        account_id='acct_'+uuid4().hex
        try:
            with self.connection() as db:
                db.execute('INSERT INTO accounts VALUES (?,?,?,?,?)',(account_id,handle,salt.hex(),digest,self.clock()))
        except sqlite3.IntegrityError:raise AccountError(409,'handle_taken') from None
        return {'id':account_id,'handle':handle}

    def authenticate(self,handle,password):
        handle=self._handle(handle)
        password=self._password(password)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            now=self.clock()
            attempt=db.execute('SELECT * FROM login_attempts WHERE handle=?',(handle,)).fetchone()
            if attempt and attempt['blocked_until']>now:raise AccountError(429,'login_temporarily_limited')
            row=db.execute('SELECT * FROM accounts WHERE handle=?',(handle,)).fetchone()
            salt=bytes.fromhex(row['salt']) if row else b'\0'*24
            expected=row['password_hash'] if row else '0'*64
            valid=hmac.compare_digest(self._hash_password(password,salt),expected)
            if not valid:
                active=bool(attempt and attempt['window_start']>now-900)
                failures=(attempt['failures'] if active else 0)+1
                window_start=attempt['window_start'] if active else now
                db.execute('INSERT INTO login_attempts VALUES (?,?,?,?) ON CONFLICT(handle) DO UPDATE SET failures=excluded.failures,window_start=excluded.window_start,blocked_until=excluded.blocked_until',
                           (handle,failures,window_start,now+900 if failures>=5 else 0))
                # An expected authentication failure must commit the limit counter.
            else:
                db.execute('DELETE FROM login_attempts WHERE handle=?',(handle,))
        if not valid:raise AccountError(401,'invalid_credentials')
        return self._public(row)

    @staticmethod
    def _token_hash(token):return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @staticmethod
    def csrf_token(token):return hmac.new(token.encode('utf-8'),b'campusfood-csrf-v1',hashlib.sha256).hexdigest()

    def issue_session(self,account_id):
        token=secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM account_sessions WHERE expires_at<=?',(self.clock(),))
            db.execute('INSERT INTO account_sessions VALUES (?,?,?)',(self._token_hash(token),account_id,self.clock()+SESSION_SECONDS))
            db.execute('DELETE FROM account_sessions WHERE token_hash IN (SELECT token_hash FROM account_sessions WHERE account_id=? ORDER BY expires_at DESC LIMIT -1 OFFSET 10)',(account_id,))
        return token

    def resolve_session(self,token):
        if not token or not isinstance(token,str) or len(token)>128:return None
        with self.connection() as db:
            row=db.execute('''SELECT a.id,a.handle FROM account_sessions s
                JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=? AND s.expires_at>?''',
                (self._token_hash(token),self.clock())).fetchone()
        return self._public(row) if row else None

    def logout(self,token):
        if token:
            with self.connection() as db:db.execute('DELETE FROM account_sessions WHERE token_hash=?',(self._token_hash(token),))

    def bind_conversation(self,account_id,session_id,title):
        now=self.clock()
        with self.connection() as db:
            db.execute('INSERT INTO product_conversations VALUES (?,?,?,?,?)',
                       (session_id,account_id,title[:80],now,now))

    def owns_conversation(self,account_id,session_id):
        with self.connection() as db:
            return db.execute('SELECT 1 FROM product_conversations WHERE account_id=? AND session_id=?',
                              (account_id,session_id)).fetchone() is not None

    def touch_conversation(self,account_id,session_id,title=None):
        with self.connection() as db:
            if title is None:
                db.execute('UPDATE product_conversations SET updated_at=? WHERE account_id=? AND session_id=?',
                           (self.clock(),account_id,session_id))
            else:
                db.execute('UPDATE product_conversations SET updated_at=?,title=? WHERE account_id=? AND session_id=?',
                           (self.clock(),title[:80],account_id,session_id))

    def list_conversations(self,account_id,limit=30):
        with self.connection() as db:
            rows=db.execute('''SELECT session_id,title,created_at,updated_at FROM product_conversations
                WHERE account_id=? ORDER BY updated_at DESC LIMIT ?''',(account_id,limit)).fetchall()
        return [dict(row) for row in rows]
