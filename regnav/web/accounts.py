"""Local demo profiles and opaque server sessions. No real university identities."""
import hashlib
import secrets
import sqlite3
import time
from pathlib import Path

DEMO_USERS = [
    ('employee-demo', 'employee', 'Марина Демонстрационная', 'Специалист деканата', 'Учебный офис', 'ТН-00001', 'employee@example.invalid'),
    ('teacher-demo', 'teacher', 'Алексей Примеров', 'Преподаватель', 'Демонстрационная кафедра', 'ТН-00002', 'teacher@example.invalid'),
]


class Accounts:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL,
                    position TEXT NOT NULL, unit TEXT NOT NULL, tab_no TEXT NOT NULL, email TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(id), expires REAL NOT NULL);
            ''')
            db.executemany('INSERT OR IGNORE INTO profiles VALUES (?,?,?,?,?,?,?)', DEMO_USERS)
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def profiles(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM profiles ORDER BY id')]

    def login(self, user_id):
        # Only the explicitly advertised demo accounts can be selected without a password.
        if user_id not in {row[0] for row in DEMO_USERS}:
            return None
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (self.digest(token), user_id, time.time() + 8 * 3600))
        return token

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def current(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute('SELECT p.* FROM profiles p JOIN sessions s ON p.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                             (self.digest(token), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (self.digest(token or ''),))
