import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DATA, DEFAULT_SETTINGS


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, directory=DATA):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'workspace.sqlite3'
        self.lock = threading.RLock()
        with self.connect() as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, created TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, type TEXT, ref TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS registrations (id TEXT PRIMARY KEY, created TEXT, verification_id TEXT UNIQUE, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);''')
            con.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (json.dumps(DEFAULT_SETTINGS),))

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def audit(self, event, detail, ref='SYSTEM'):
        with self.lock, self.connect() as con:
            con.execute('INSERT INTO audit(created,type,ref,detail) VALUES(?,?,?,?)', (utcnow(), event, ref, detail))

    def events(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 500')]

    def results(self):
        with self.connect() as con:
            return [json.loads(r['payload']) for r in con.execute('SELECT payload FROM results ORDER BY created DESC LIMIT 500')]

    def result(self, result_id):
        with self.connect() as con:
            r = con.execute('SELECT payload FROM results WHERE id=?', (result_id,)).fetchone()
            return json.loads(r['payload']) if r else None

    def save_result(self, result):
        with self.lock, self.connect() as con:
            con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)', (result['id'], result['created'], json.dumps(result, ensure_ascii=False)))

    def update_result(self, result_id, changes):
        with self.lock:
            result = self.result(result_id)
            if not result:
                raise ValueError('Permohonan tidak ditemukan.')
            if result['status'] not in ['manual', 'scheduled']:
                raise ValueError('Permohonan sudah selesai atau bukan antrean manual.')
            result.update(changes)
            self.save_result(result)
            return result

    def settings(self):
        with self.connect() as con:
            return json.loads(con.execute('SELECT payload FROM settings WHERE id=1').fetchone()['payload'])

    def set_settings(self, settings):
        with self.lock, self.connect() as con:
            con.execute('UPDATE settings SET payload=? WHERE id=1', (json.dumps(settings),))
        self.audit('Konfigurasi diperbarui', json.dumps(settings))

    def save_registration(self, record):
        with self.lock, self.connect() as con:
            con.execute('INSERT INTO registrations VALUES (?,?,?,?)', (record['id'], record['created'], record['verification_id'], json.dumps(record, ensure_ascii=False)))

    def registration(self, registration_id):
        with self.connect() as con:
            row = con.execute('SELECT payload FROM registrations WHERE id=?', (registration_id,)).fetchone()
            return json.loads(row['payload']) if row else None

    def registration_for_verification(self, verification_id):
        with self.connect() as con:
            row = con.execute('SELECT payload FROM registrations WHERE verification_id=?', (verification_id,)).fetchone()
            return json.loads(row['payload']) if row else None
