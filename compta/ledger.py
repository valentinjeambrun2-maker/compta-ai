"""Moteur de comptabilité en partie double + états financiers + FEC."""
import datetime as dt

class LedgerError(ValueError):
    pass

def cents(x):
    """Euros (float/str) -> centimes (int), arrondi commercial."""
    if isinstance(x, int):
        return x * 100
    s = str(x).replace(" ", "").replace(" ", "").replace("€", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    from decimal import Decimal, ROUND_HALF_UP
    return int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def euros(c):
    return round((c or 0) / 100, 2)

def _check_date(d):
    try:
        dt.date.fromisoformat(d)
    except Exception:
        raise LedgerError(f"Date invalide : {d!r} (format AAAA-MM-JJ attendu)")

def entity(con, eid):
    r = con.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
    if not r:
        raise LedgerError("Dossier introuvable")
    return dict(r)

def account_codes(con, eid):
    return {r["code"]: r["label"] for r in con.execute("SELECT code,label FROM accounts WHERE entity_id=?", (eid,))}

def post_entry(con, eid, date, journal, label, lines, ref=None, source="manual"):
    """lines: [{account, debit, credit, label?, rate?, base?}] en centimes. Refuse toute écriture déséquilibrée."""
    _check_date(date)
    ent = entity(con, eid)
    if ent["closed_until"] and date <= ent["closed_until"]:
        raise LedgerError(f"Période clôturée jusqu'au {ent['closed_until']} : écriture interdite")
    if len(lines) < 2:
        raise LedgerError("Une écriture doit comporter au moins deux lignes")
    codes = account_codes(con, eid)
    td = tc = 0
    for l in lines:
        d, c = int(l.get("debit") or 0), int(l.get("credit") or 0)
        if d < 0 or c < 0 or (d and c):
            raise LedgerError("Chaque ligne est soit au débit, soit au crédit, en positif")
        if l["account"] not in codes:
            raise LedgerError(f"Compte inconnu : {l['account']}")
        td += d; tc += c
    if td != tc or td == 0:
        raise LedgerError(f"Écriture déséquilibrée : débit {euros(td)} ≠ crédit {euros(tc)}")
    cur = con.execute("INSERT INTO entries(entity_id,date,journal,label,ref,source) VALUES(?,?,?,?,?,?)",
                      (eid, date, journal, label, ref, source))
    en = cur.lastrowid
    con.executemany("INSERT INTO lines(entry_id,account,label,debit,credit,rate,base) VALUES(?,?,?,?,?,?,?)",
                    [(en, l["account"], l.get("label") or label, int(l.get("debit") or 0), int(l.get("credit") or 0),
                      l.get("rate"), l.get("base")) for l in lines if (l.get("debit") or l.get("credit"))])
    return en

def _period(start, end):
    return (start or "0000-01-01", end or "9999-12-31")

def balances(con, eid, start=None, end=None, prefix=""):
    s, e = _period(start, end)
    rows = con.execute("""SELECT l.account, a.label, SUM(l.debit) d, SUM(l.credit) c
        FROM lines l JOIN entries en ON en.id=l.entry_id
        LEFT JOIN accounts a ON a.entity_id=en.entity_id AND a.code=l.account
        WHERE en.entity_id=? AND en.date BETWEEN ? AND ? AND l.account LIKE ?
        GROUP BY l.account ORDER BY l.account""", (eid, s, e, prefix + "%")).fetchall()
    return [{"account": r["account"], "label": r["label"], "debit": r["d"], "credit": r["c"], "solde": r["d"] - r["c"]} for r in rows]

def solde(con, eid, prefix, start=None, end=None):
    return sum(b["solde"] for b in balances(con, eid, start, end, prefix))

def trial_balance(con, eid, start=None, end=None):
    rows = balances(con, eid, start, end)
    return {"rows": rows, "total_debit": sum(r["debit"] for r in rows), "total_credit": sum(r["credit"] for r in rows)}

def journal(con, eid, start=None, end=None, limit=500):
    s, e = _period(start, end)
    out = []
    for en in con.execute("SELECT * FROM entries WHERE entity_id=? AND date BETWEEN ? AND ? ORDER BY date DESC,id DESC LIMIT ?", (eid, s, e, limit)):
        ls = [dict(l) for l in con.execute("SELECT account,label,debit,credit FROM lines WHERE entry_id=?", (en["id"],))]
        out.append({**dict(en), "lines": ls})
    return out

def grand_livre(con, eid, account, start=None, end=None):
    s, e = _period(start, end)
    rows, run = [], 0
    for r in con.execute("""SELECT en.id,en.date,en.journal,en.label,l.debit,l.credit FROM lines l JOIN entries en ON en.id=l.entry_id
        WHERE en.entity_id=? AND l.account=? AND en.date BETWEEN ? AND ? ORDER BY en.date,en.id""", (eid, account, s, e)):
        run += r["debit"] - r["credit"]
        rows.append({**dict(r), "cumul": run})
    return rows

def income_statement(con, eid, start=None, end=None):
    charges = [{**b, "montant": b["solde"]} for b in balances(con, eid, start, end, "6")]
    produits = [{**b, "montant": -b["solde"]} for b in balances(con, eid, start, end, "7")]
    tc, tp = sum(c["montant"] for c in charges), sum(p["montant"] for p in produits)
    return {"charges": charges, "produits": produits, "total_charges": tc, "total_produits": tp, "resultat": tp - tc}

def balance_sheet(con, eid, end=None):
    actif, passif = [], []
    for b in balances(con, eid, None, end):
        if b["account"][0] in "12345" and b["solde"]:
            (actif if b["solde"] > 0 else passif).append({**b, "montant": abs(b["solde"])})
    res = income_statement(con, eid, None, end)["resultat"]
    passif.append({"account": "12", "label": "Résultat de l'exercice (cumul)", "montant": res})
    ta, tp = sum(a["montant"] for a in actif), sum(p["montant"] for p in passif)
    return {"actif": actif, "passif": passif, "total_actif": ta, "total_passif": tp, "equilibre": ta == tp}

def fec(con, eid, year):
    """Fichier des Écritures Comptables (art. A47 A-1 LPF), séparateur tabulation."""
    jl = {"VE": "Ventes", "AC": "Achats", "BQ": "Banque", "OD": "Opérations diverses", "AN": "A-nouveaux"}
    head = ["JournalCode","JournalLib","EcritureNum","EcritureDate","CompteNum","CompteLib","CompAuxNum","CompAuxLib",
            "PieceRef","PieceDate","EcritureLib","Debit","Credit","EcritureLet","DateLet","ValidDate","Montantdevise","Idevise"]
    out = ["\t".join(head)]
    fmt = lambda c: f"{c/100:.2f}".replace(".", ",")
    for r in con.execute("""SELECT en.id,en.date,en.journal,en.label el,en.ref,l.account,a.label al,l.debit,l.credit
        FROM lines l JOIN entries en ON en.id=l.entry_id LEFT JOIN accounts a ON a.entity_id=en.entity_id AND a.code=l.account
        WHERE en.entity_id=? AND substr(en.date,1,4)=? ORDER BY en.date,en.id,l.id""", (eid, str(year))):
        d = r["date"].replace("-", "")
        clean = lambda s: (s or "").replace("\t", " ").replace("\n", " ")
        out.append("\t".join([r["journal"], jl.get(r["journal"], r["journal"]), str(r["id"]), d, r["account"], clean(r["al"]),
                              "", "", clean(r["ref"] or str(r["id"])), d, clean(r["el"]), fmt(r["debit"]), fmt(r["credit"]),
                              "", "", d, "", "EUR"]))
    return "\n".join(out) + "\n"
