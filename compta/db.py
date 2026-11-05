"""Base SQLite. Tous les montants sont stockés en centimes (entiers)."""
import os, sqlite3, threading

DB_PATH = os.environ.get("COMPTA_DB", os.path.join(os.path.dirname(__file__), "..", "data", "compta.db"))
LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN('entreprise','particulier')),
  legal_form TEXT DEFAULT 'SASU', tva_regime TEXT DEFAULT 'reel', siret TEXT, address TEXT,
  closed_until TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS accounts(
  entity_id INTEGER NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL, tva_rate REAL DEFAULT 0,
  PRIMARY KEY(entity_id, code));
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, date TEXT NOT NULL, journal TEXT NOT NULL,
  label TEXT NOT NULL, ref TEXT, source TEXT DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS lines(
  id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  account TEXT NOT NULL, label TEXT, debit INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0,
  rate REAL, base INTEGER, CHECK(debit>=0 AND credit>=0));
CREATE TABLE IF NOT EXISTS bank_tx(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, date TEXT NOT NULL, label TEXT NOT NULL,
  amount INTEGER NOT NULL, account TEXT, tva_rate REAL DEFAULT 0, status TEXT DEFAULT 'pending',
  confidence REAL, reason TEXT, entry_id INTEGER, invoice_id INTEGER);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN('sale','purchase')),
  number TEXT NOT NULL, date TEXT NOT NULL, due TEXT, party TEXT NOT NULL, ht INTEGER, tva INTEGER, ttc INTEGER,
  status TEXT DEFAULT 'open', lines TEXT, account TEXT, entry_id INTEGER, pay_entry_id INTEGER);
CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, label TEXT, date TEXT, cost INTEGER, years INTEGER,
  amortized INTEGER DEFAULT 0, last_year INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS declarations(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, type TEXT, period TEXT, data TEXT,
  status TEXT DEFAULT 'brouillon', created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_entries ON entries(entity_id, date);
CREATE INDEX IF NOT EXISTS ix_lines ON lines(entry_id, account);
"""

def connect(path=None):
    path = path or DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con
