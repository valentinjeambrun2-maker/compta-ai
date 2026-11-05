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
CREATE TABLE IF NOT EXISTS bank_rules(
  entity_id INTEGER NOT NULL, rule_key TEXT NOT NULL, account TEXT NOT NULL, tva_rate REAL DEFAULT 0,
  hits INTEGER DEFAULT 1, updated TEXT, PRIMARY KEY(entity_id, rule_key));
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
CREATE TABLE IF NOT EXISTS settings(entity_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY(entity_id,key));
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, nom TEXT, prenom TEXT, nir TEXT, naissance TEXT, adresse TEXT,
  emploi TEXT, statut TEXT DEFAULT 'non-cadre', contrat TEXT DEFAULT 'CDI', date_entree TEXT, date_sortie TEXT,
  brut INTEGER, heures REAL DEFAULT 151.67, taux_pas REAL, mutuelle INTEGER DEFAULT 0, actif INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS payslips(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, employee_id INTEGER NOT NULL, period TEXT NOT NULL,
  data TEXT, entry_id INTEGER, UNIQUE(employee_id, period));
CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, number TEXT, date TEXT, valid_until TEXT, party TEXT, email TEXT,
  lines TEXT, ht INTEGER, tva INTEGER, ttc INTEGER, status TEXT DEFAULT 'brouillon', invoice_id INTEGER);
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, date TEXT, person TEXT, beneficiaire TEXT DEFAULT 'dirigeant',
  label TEXT, account TEXT, ttc INTEGER, tva_rate REAL DEFAULT 0, km REAL, cv INTEGER, file_name TEXT, file_mime TEXT,
  file_data BLOB, status TEXT DEFAULT 'a_valider', entry_id INTEGER, pay_entry_id INTEGER);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, invoice_id INTEGER, level INTEGER, sent_at TEXT, channel TEXT, recipient TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS edi_submissions(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, declaration_id INTEGER, type TEXT, mode TEXT, ref TEXT,
  status TEXT, response TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, pwd TEXT NOT NULL, is_admin INTEGER DEFAULT 0,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS memberships(
  user_id INTEGER NOT NULL, entity_id INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN('proprietaire','comptable','lecteur')),
  PRIMARY KEY(user_id, entity_id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, user_id INTEGER, entity_id INTEGER, action TEXT, detail TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tiers(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, type TEXT NOT NULL CHECK(type IN('client','fournisseur')), nom TEXT NOT NULL,
  account TEXT NOT NULL, siren TEXT, tva_intra TEXT, pays TEXT DEFAULT 'FR', email TEXT, telephone TEXT, adresse TEXT,
  delai_jours INTEGER DEFAULT 30, notes TEXT, UNIQUE(entity_id, account));
CREATE TABLE IF NOT EXISTS attachments(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, entry_id INTEGER, invoice_id INTEGER, name TEXT, mime TEXT, data BLOB,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS bank_statements(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, account TEXT DEFAULT '512', date TEXT NOT NULL, solde INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS profiles(
  entity_id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}', completed INTEGER DEFAULT 0, updated TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tax_documents(
  id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, year INTEGER, kind TEXT, name TEXT, mime TEXT, data BLOB,
  extracted TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS budgets(entity_id INTEGER NOT NULL, year INTEGER NOT NULL, account TEXT NOT NULL, month INTEGER NOT NULL,
  amount INTEGER NOT NULL, PRIMARY KEY(entity_id, year, account, month));
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
    migrate(con)
    return con

# Colonnes ajoutées après la v1 : appliquées aux bases existantes
COLUMNS = {
    "entities": [("tva_exigibilite", "TEXT DEFAULT 'debits'"), ("email", "TEXT")],
    "invoices": [("nature", "TEXT DEFAULT 'services'"), ("email", "TEXT"), ("quote_id", "INTEGER"), ("tiers_id", "INTEGER"),
                 ("tiers_account", "TEXT"), ("operation", "TEXT DEFAULT 'france'")],
    "lines": [("lettrage", "TEXT"), ("date_lettrage", "TEXT"), ("pointe", "INTEGER DEFAULT 0")],
    "entries": [("piece_date", "TEXT"), ("created_by", "INTEGER"), ("reversal_of", "INTEGER")],
}

def migrate(con):
    for table, cols in COLUMNS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    from . import pcg
    for r in con.execute("SELECT id, kind FROM entities").fetchall():
        pcg.seed(con, r[0], r[1])
    con.commit()

def get_setting(con, eid, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE entity_id=? AND key=?", (eid, key)).fetchone()
    return r[0] if r and r[0] not in (None, "") else default

def set_setting(con, eid, key, value):
    con.execute("INSERT INTO settings(entity_id,key,value) VALUES(?,?,?) ON CONFLICT(entity_id,key) DO UPDATE SET value=excluded.value",
                (eid, key, None if value is None else str(value)))
