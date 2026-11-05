"""Utilisateurs, sessions, rôles par dossier et journal d'audit.

Rôles par dossier :
  - proprietaire : tout, y compris la gestion des membres ;
  - comptable    : saisie, validation, déclarations, clôture, paramètres (pas la gestion des membres) ;
  - lecteur      : consultation et exports uniquement.
Mots de passe : PBKDF2-SHA256 (600 000 itérations, sel aléatoire). Jetons de session : seule leur
empreinte SHA-256 est stockée. Verrouillage temporaire après 5 échecs de connexion.
"""
import hashlib, hmac, secrets, time, datetime as dt, re
from . import ledger

ROLES = ("proprietaire", "comptable", "lecteur")
ITER = 600_000
SESSION_DAYS = 7
_FAILS = {}

class AuthError(PermissionError):
    pass

def hash_password(pwd):
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt, ITER)
    return f"pbkdf2_sha256${ITER}${salt.hex()}${h.hex()}"

def check_password(pwd, stored):
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pwd.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False

def _valid_email(e):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e or ""))

def create_user(con, email, name, password, is_admin=False):
    email = (email or "").strip().lower()
    if not _valid_email(email):
        raise ledger.LedgerError("Adresse e-mail invalide")
    if len(password or "") < 8:
        raise ledger.LedgerError("Le mot de passe doit contenir au moins 8 caractères")
    if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise ledger.LedgerError("Un compte existe déjà avec cet e-mail")
    return con.execute("INSERT INTO users(email,name,pwd,is_admin) VALUES(?,?,?,?)", (email, name or email.split("@")[0], hash_password(password), int(is_admin))).lastrowid

def needs_setup(con):
    return con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

def setup(con, email, name, password):
    """Premier lancement : crée l'administrateur et lui rattache les dossiers existants."""
    if not needs_setup(con):
        raise AuthError("L'installation est déjà initialisée")
    uid = create_user(con, email, name, password, True)
    for (eid,) in con.execute("SELECT id FROM entities").fetchall():
        con.execute("INSERT OR IGNORE INTO memberships(user_id,entity_id,role) VALUES(?,?,'proprietaire')", (uid, eid))
    return uid

def _tok_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()

def login(con, email, password):
    email = (email or "").strip().lower()
    now = time.time()
    fails = [t for t in _FAILS.get(email, []) if now - t < 900]
    if len(fails) >= 5:
        raise AuthError("Trop de tentatives : réessayez dans 15 minutes")
    u = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u or not check_password(password or "", u["pwd"]):
        _FAILS[email] = fails + [now]
        raise AuthError("E-mail ou mot de passe incorrect")
    _FAILS.pop(email, None)
    tok = secrets.token_urlsafe(32)
    exp = (dt.datetime.utcnow() + dt.timedelta(days=SESSION_DAYS)).isoformat()
    con.execute("DELETE FROM sessions WHERE expires<?", (dt.datetime.utcnow().isoformat(),))
    con.execute("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", (_tok_hash(tok), u["id"], exp))
    return tok, public_user(u)

def logout(con, tok):
    con.execute("DELETE FROM sessions WHERE token=?", (_tok_hash(tok or ""),))

def user_from_token(con, tok):
    if not tok:
        return None
    r = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?",
                    (_tok_hash(tok), dt.datetime.utcnow().isoformat())).fetchone()
    return dict(r) if r else None

def public_user(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"])}

def change_password(con, uid, old, new):
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not check_password(old or "", u["pwd"]):
        raise AuthError("Mot de passe actuel incorrect")
    if len(new or "") < 8:
        raise ledger.LedgerError("Le nouveau mot de passe doit contenir au moins 8 caractères")
    con.execute("UPDATE users SET pwd=? WHERE id=?", (hash_password(new), uid))
    con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))

def role(con, user, eid):
    if not user:
        return None
    if user.get("is_admin"):
        return "proprietaire"
    r = con.execute("SELECT role FROM memberships WHERE user_id=? AND entity_id=?", (user["id"], eid)).fetchone()
    return r[0] if r else None

def require(con, user, eid, level):
    """level : 'lecture' | 'ecriture' | 'membres'."""
    r = role(con, user, eid)
    if not r:
        raise AuthError("Accès refusé à ce dossier")
    if level == "ecriture" and r == "lecteur":
        raise AuthError("Votre rôle (lecteur) ne permet pas de modifier ce dossier")
    if level == "membres" and r != "proprietaire":
        raise AuthError("Seul le propriétaire du dossier peut gérer ses membres")
    return r

def entities_for(con, user):
    if user.get("is_admin"):
        rows = con.execute("SELECT e.*, 'proprietaire' AS role FROM entities e ORDER BY e.id")
    else:
        rows = con.execute("SELECT e.*, m.role FROM entities e JOIN memberships m ON m.entity_id=e.id WHERE m.user_id=? ORDER BY e.id", (user["id"],))
    return [dict(r) for r in rows]

def members(con, eid):
    return [dict(r) for r in con.execute("""SELECT u.id, u.email, u.name, m.role FROM memberships m JOIN users u ON u.id=m.user_id
                                            WHERE m.entity_id=? ORDER BY m.role, u.email""", (eid,))]

def add_member(con, eid, email, role_, name=None):
    """Ajoute un membre. Crée le compte si besoin avec un mot de passe provisoire (renvoyé une seule fois)."""
    if role_ not in ROLES:
        raise ledger.LedgerError("Rôle invalide")
    email = (email or "").strip().lower()
    u = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    temp = None
    if not u:
        temp = secrets.token_urlsafe(9)
        uid = create_user(con, email, name, temp)
    else:
        uid = u["id"]
    con.execute("INSERT INTO memberships(user_id,entity_id,role) VALUES(?,?,?) ON CONFLICT(user_id,entity_id) DO UPDATE SET role=excluded.role", (uid, eid, role_))
    return {"user_id": uid, "email": email, "role": role_, "mot_de_passe_provisoire": temp}

def remove_member(con, eid, uid, current_uid):
    owners = con.execute("SELECT COUNT(*) FROM memberships WHERE entity_id=? AND role='proprietaire'", (eid,)).fetchone()[0]
    r = con.execute("SELECT role FROM memberships WHERE entity_id=? AND user_id=?", (eid, uid)).fetchone()
    if r and r[0] == "proprietaire" and owners <= 1:
        raise ledger.LedgerError("Impossible de retirer le dernier propriétaire du dossier")
    con.execute("DELETE FROM memberships WHERE entity_id=? AND user_id=?", (eid, uid))

def log(con, uid, eid, action, detail=""):
    con.execute("INSERT INTO audit_log(user_id,entity_id,action,detail) VALUES(?,?,?,?)", (uid, eid or None, action, (detail or "")[:500]))

def audit_trail(con, eid, limit=200):
    return [dict(r) for r in con.execute("""SELECT a.at, a.action, a.detail, u.email FROM audit_log a LEFT JOIN users u ON u.id=a.user_id
                                            WHERE a.entity_id=? ORDER BY a.id DESC LIMIT ?""", (eid, limit))]
