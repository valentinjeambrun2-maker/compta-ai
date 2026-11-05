"""Tiers (clients / fournisseurs) avec comptes auxiliaires, lettrage et balance âgée.

Chaque tiers reçoit un compte individuel 411xxxx (client) ou 401xxxx (fournisseur) : tous les calculs par
préfixe (créances clients, dettes fournisseurs, liasse) restent justes, et chaque tiers a son grand livre.
Le lettrage rapproche les lignes débit / crédit d'un même compte de tiers dont la somme est nulle
(facture ↔ règlement) ; il est automatique au règlement et peut être lancé ou défait manuellement.
"""
import re, datetime as dt, itertools
from . import ledger

PREFIX = {"client": "411", "fournisseur": "401"}

def _slug(nom):
    import unicodedata
    s = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s[:6] or "TIERS"

def find_or_create(con, eid, type_, nom, **kw):
    if type_ not in PREFIX:
        raise ledger.LedgerError("Type de tiers invalide")
    nom = (nom or "").strip() or "Divers"
    r = con.execute("SELECT * FROM tiers WHERE entity_id=? AND type=? AND lower(nom)=lower(?)", (eid, type_, nom)).fetchone()
    if r:
        upd = {k: v for k, v in kw.items() if v and not r[k]}
        for k, v in upd.items():
            con.execute(f"UPDATE tiers SET {k}=? WHERE id=?", (v, r["id"]))
        return dict(r)
    base = PREFIX[type_] + _slug(nom)
    acc, i = base, 1
    while con.execute("SELECT 1 FROM accounts WHERE entity_id=? AND code=?", (eid, acc)).fetchone():
        i += 1; acc = f"{base}{i}"
    label = ("Client " if type_ == "client" else "Fournisseur ") + nom
    con.execute("INSERT INTO accounts(entity_id,code,label,tva_rate) VALUES(?,?,?,0)", (eid, acc, label))
    allowed = ("siren", "tva_intra", "pays", "email", "telephone", "adresse", "delai_jours", "notes")
    vals = {k: kw[k] for k in allowed if kw.get(k) not in (None, "")}
    cols = ", ".join(["entity_id", "type", "nom", "account"] + list(vals))
    tid = con.execute(f"INSERT INTO tiers({cols}) VALUES({', '.join('?' * (4 + len(vals)))})", (eid, type_, nom, acc, *vals.values())).lastrowid
    return dict(con.execute("SELECT * FROM tiers WHERE id=?", (tid,)).fetchone())

def update(con, eid, tid, data):
    allowed = ("nom", "siren", "tva_intra", "pays", "email", "telephone", "adresse", "delai_jours", "notes")
    for k, v in data.items():
        if k in allowed:
            con.execute(f"UPDATE tiers SET {k}=? WHERE id=? AND entity_id=?", (v, tid, eid))

def listing(con, eid, type_=None):
    out = []
    for t in con.execute("SELECT * FROM tiers WHERE entity_id=? AND (? IS NULL OR type=?) ORDER BY nom", (eid, type_, type_)):
        s = ledger.solde(con, eid, t["account"])
        nb = con.execute("SELECT COUNT(*), COALESCE(SUM(ttc),0) FROM invoices WHERE entity_id=? AND tiers_id=?", (eid, t["id"])).fetchone()
        out.append({**dict(t), "solde": s if t["type"] == "client" else -s, "nb_factures": nb[0], "ca_ttc": nb[1]})
    return out

# ---------------- Lettrage ----------------
def _next_code(con, eid, account):
    used = {r[0] for r in con.execute("""SELECT DISTINCT l.lettrage FROM lines l JOIN entries e ON e.id=l.entry_id
                                         WHERE e.entity_id=? AND l.account=? AND l.lettrage IS NOT NULL""", (eid, account))}
    for n in itertools.count():
        code, x = "", n
        while True:
            code = chr(65 + x % 26) + code
            x = x // 26 - 1
            if x < 0:
                break
        code = code.rjust(2, "A")
        if code not in used:
            return code

def letter(con, eid, line_ids, date=None):
    """Lettre un ensemble de lignes d'un même compte dont la somme débit - crédit est nulle."""
    if len(line_ids) < 2:
        raise ledger.LedgerError("Sélectionnez au moins deux lignes")
    q = ",".join("?" * len(line_ids))
    rows = con.execute(f"""SELECT l.* FROM lines l JOIN entries e ON e.id=l.entry_id WHERE e.entity_id=? AND l.id IN ({q})""", (eid, *line_ids)).fetchall()
    if len(rows) != len(line_ids):
        raise ledger.LedgerError("Ligne introuvable")
    if len({r["account"] for r in rows}) != 1:
        raise ledger.LedgerError("Les lignes doivent appartenir au même compte")
    if any(r["lettrage"] for r in rows):
        raise ledger.LedgerError("Une des lignes est déjà lettrée")
    if sum(r["debit"] - r["credit"] for r in rows) != 0:
        raise ledger.LedgerError("Lettrage impossible : les lignes ne s'équilibrent pas")
    code = _next_code(con, eid, rows[0]["account"])
    con.execute(f"UPDATE lines SET lettrage=?, date_lettrage=? WHERE id IN ({q})", (code, date or dt.date.today().isoformat(), *line_ids))
    return code

def unletter(con, eid, account, code):
    con.execute("""UPDATE lines SET lettrage=NULL, date_lettrage=NULL WHERE account=? AND lettrage=? AND entry_id IN
                   (SELECT id FROM entries WHERE entity_id=?)""", (account, code, eid))

def open_lines(con, eid, account):
    return [dict(r) for r in con.execute("""SELECT l.id, l.debit, l.credit, l.lettrage, e.date, e.label, e.ref, e.journal FROM lines l
        JOIN entries e ON e.id=l.entry_id WHERE e.entity_id=? AND l.account=? ORDER BY e.date, l.id""", (eid, account))]

def auto_letter(con, eid, account=None):
    """Lettrage automatique : 1) même référence de pièce, 2) montants opposés identiques (le plus ancien d'abord)."""
    accs = [account] if account else [r[0] for r in con.execute("SELECT account FROM tiers WHERE entity_id=?", (eid,))]
    done = 0
    for acc in accs:
        lines = [l for l in open_lines(con, eid, acc) if not l["lettrage"]]
        by_ref = {}
        for l in lines:
            if l["ref"]:
                by_ref.setdefault(l["ref"], []).append(l)
        used = set()
        for ref, grp in by_ref.items():
            if len(grp) >= 2 and sum(l["debit"] - l["credit"] for l in grp) == 0:
                letter(con, eid, [l["id"] for l in grp]); used |= {l["id"] for l in grp}; done += 1
        rest = [l for l in lines if l["id"] not in used]
        deb = [l for l in rest if l["debit"]]
        cre = [l for l in rest if l["credit"]]
        for d in deb:
            m = next((c for c in cre if c["credit"] == d["debit"] and c["id"] not in used), None)
            if m:
                letter(con, eid, [d["id"], m["id"]]); used |= {d["id"], m["id"]}; done += 1
    return {"lettrages": done}

# ---------------- Balance âgée ----------------
def aged_balance(con, eid, type_="client", today=None):
    """Créances (ou dettes) non lettrées par ancienneté d'échéance."""
    today = today or dt.date.today().isoformat()
    t0 = dt.date.fromisoformat(today)
    buckets = ["non échu", "0-30 j", "31-60 j", "61-90 j", "> 90 j"]
    out = []
    for t in con.execute("SELECT * FROM tiers WHERE entity_id=? AND type=?", (eid, type_)):
        row = {"tiers": t["nom"], "account": t["account"], **{b: 0 for b in buckets}, "total": 0}
        for inv in con.execute("SELECT * FROM invoices WHERE entity_id=? AND tiers_id=? AND status='open'", (eid, t["id"])):
            late = (t0 - dt.date.fromisoformat(inv["due"])).days
            b = buckets[0] if late <= 0 else buckets[1] if late <= 30 else buckets[2] if late <= 60 else buckets[3] if late <= 90 else buckets[4]
            row[b] += inv["ttc"]; row["total"] += inv["ttc"]
        if row["total"]:
            out.append(row)
    tot = {"tiers": "TOTAL", "account": "", **{b: sum(r[b] for r in out) for b in buckets}, "total": sum(r["total"] for r in out)}
    return {"colonnes": buckets, "lignes": sorted(out, key=lambda r: -r["total"]), "total": tot}

def risk_score(con, eid, tid):
    """Score de risque client 0-100 (retards de paiement historiques, encours)."""
    invs = con.execute("SELECT i.*, (SELECT e.date FROM entries e WHERE e.id=i.pay_entry_id) paid_on FROM invoices i WHERE entity_id=? AND tiers_id=?", (eid, tid)).fetchall()
    if not invs:
        return {"score": 50, "commentaire": "Aucun historique"}
    delays = []
    for i in invs:
        if i["paid_on"]:
            delays.append((dt.date.fromisoformat(i["paid_on"]) - dt.date.fromisoformat(i["due"])).days)
        elif i["due"] < dt.date.today().isoformat():
            delays.append((dt.date.today() - dt.date.fromisoformat(i["due"])).days)
    avg = sum(delays) / len(delays) if delays else 0
    score = max(0, min(100, round(100 - max(0, avg) * 1.5)))
    return {"score": score, "retard_moyen_jours": round(avg, 1),
            "commentaire": "Bon payeur" if score >= 80 else "Paie avec retard" if score >= 50 else "Risque élevé : exiger un acompte"}
