"""Import de relevés bancaires CSV, catégorisation IA, rapprochement et comptabilisation."""
import csv, io, re, unicodedata, datetime as dt
from collections import Counter
from . import ledger, ai

def _norm(h):
    h = (h or "").strip().lower()
    for a, b in (("é","e"),("è","e"),("ê","e"),("û","u")):
        h = h.replace(a, b)
    return h

def _date(s):
    s = s.strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    raise ledger.LedgerError(f"Date non reconnue : {s!r}")

def parse_csv(text):
    text = text.lstrip("﻿")
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    if "\t" in sample.splitlines()[0]:
        delim = "\t"
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    head = [_norm(h) for h in rows[0]]
    find = lambda *keys: next((i for i, h in enumerate(head) if any(k in h for k in keys)), None)
    i_date, i_lab = find("date"), find("libell", "label", "descr", "intitul", "operation")
    i_amt, i_deb, i_cre = find("montant", "amount", "somme"), find("debit"), find("credit")
    if i_date is None or i_lab is None or (i_amt is None and i_deb is None and i_cre is None):
        raise ledger.LedgerError("En-têtes CSV non reconnus : il faut Date, Libellé et Montant (ou Débit/Crédit)")
    out = []
    for r in rows[1:]:
        g = lambda i: (r[i].strip() if i is not None and i < len(r) else "")
        if i_amt is not None and g(i_amt):
            amt = ledger.cents(g(i_amt))
        else:
            d, c = g(i_deb), g(i_cre)
            amt = (ledger.cents(c) if c else 0) - (abs(ledger.cents(d)) if d else 0)
        if amt == 0:
            continue
        out.append({"date": _date(g(i_date)), "label": re.sub(r"\s+", " ", g(i_lab)), "amount": amt})
    return out

# Mots génériques des libellés bancaires, ignorés pour reconnaître un même commerçant.
_BANK_NOISE = {"cb", "carte", "prlv", "prelevement", "vir", "virement", "sepa", "paiement", "pmt", "ref",
               "les", "des", "une", "sas", "sarl", "sasu", "eurl"}

def rule_key(label, amount):
    """Clé de règle : 3 premiers mots du libellé + sens du flux.
    Dates, numéros et préfixes bancaires sont ignorés : « CB CARREFOUR 05/01 » et « CB CARREFOUR 12/02 » partagent la règle."""
    s = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode().lower()
    words = [w for w in re.findall(r"[a-z]+", s) if len(w) > 2 and w not in _BANK_NOISE]
    if not words:
        return None
    return " ".join(words[:3]) + ("|-" if amount < 0 else "|+")

def _rules(con, eid):
    return {r["rule_key"]: r for r in con.execute("SELECT rule_key, account, tva_rate FROM bank_rules WHERE entity_id=?", (eid,))}

def _remember(con, eid, label, amount, account, rate):
    """Mémorise le choix de l'utilisateur : les prochaines opérations au même libellé le reprendront."""
    key = rule_key(label, amount)
    if key:
        con.execute("""INSERT INTO bank_rules(entity_id, rule_key, account, tva_rate, hits, updated) VALUES(?,?,?,?,1,?)
                       ON CONFLICT(entity_id, rule_key) DO UPDATE SET account=excluded.account, tva_rate=excluded.tva_rate,
                       hits=hits+1, updated=excluded.updated""", (eid, key, account, rate, dt.date.today().isoformat()))

def _journal_twin(con, eid, r):
    """Écriture déjà saisie à la main sur le 512 : même montant, à 3 jours près, hors relevés déjà importés."""
    d = dt.date.fromisoformat(r["date"])
    return con.execute("""SELECT e.id, e.date FROM lines l JOIN entries e ON e.id = l.entry_id
        WHERE e.entity_id=? AND l.account='512' AND (l.debit + l.credit)=? AND e.date BETWEEN ? AND ? AND e.source != 'bank'
        ORDER BY e.date LIMIT 1""",
        (eid, abs(r["amount"]), (d - dt.timedelta(days=3)).isoformat(), (d + dt.timedelta(days=3)).isoformat())).fetchone()

def import_rows(con, eid, rows):
    """Importe en évitant les doublons (même date/libellé/montant déjà présents).
    Catégorisation : règles mémorisées d'abord, puis règles locales et IA.
    Une opération qui ressemble à une écriture déjà saisie reste en attente avec une confiance basse."""
    kind = ledger.entity(con, eid)["kind"]
    existing = Counter((r["date"], r["label"], r["amount"]) for r in
                       con.execute("SELECT date,label,amount FROM bank_tx WHERE entity_id=?", (eid,)))
    seen, fresh = Counter(), []
    for r in rows:
        k = (r["date"], r["label"], r["amount"])
        seen[k] += 1
        if seen[k] > existing[k]:
            fresh.append(r)
    chart = ledger.account_codes(con, eid)
    rules = _rules(con, eid)
    cats, todo = [None] * len(fresh), []
    for i, r in enumerate(fresh):
        rule = rules.get(rule_key(r["label"], r["amount"]))
        if rule and rule["account"] in chart:
            cats[i] = {"account": rule["account"], "tva_rate": rule["tva_rate"] or 0, "confidence": .95,
                       "reason": "Règle mémorisée : vos choix précédents pour ce libellé"}
        else:
            todo.append(i)
    if todo:
        for i, c in zip(todo, ai.categorize_batch(kind, [fresh[i] for i in todo], chart)):
            cats[i] = c
    matched, possible = set(), 0
    for r, c in zip(fresh, cats):
        inv = match_invoice(con, eid, r, matched)
        if inv:
            matched.add(inv["id"])
            c = {"account": inv["tiers_account"] or ("411" if inv["kind"] == "sale" else "401"), "tva_rate": 0, "confidence": .97,
                 "reason": f"Lettrage : règlement de la facture {inv['number']} ({inv['party']})"}
        else:
            twin = _journal_twin(con, eid, r)
            if twin:
                possible += 1
                c = {**c, "confidence": min(c["confidence"], .3),
                     "reason": f"Doublon possible : même montant saisi le {twin['date']} (écriture n°{twin['id']}). Vérifiez avant de valider."}
        con.execute("INSERT INTO bank_tx(entity_id,date,label,amount,account,tva_rate,confidence,reason,invoice_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (eid, r["date"], r["label"], r["amount"], c["account"], c["tva_rate"], c["confidence"], c["reason"], inv["id"] if inv else None))
    return {"imported": len(fresh), "duplicates": len(rows) - len(fresh),
            "rules_applied": len(fresh) - len(todo), "possible_duplicates": possible}

def match_invoice(con, eid, r, exclude=()):
    """Rapproche une opération d'une facture ouverte : numéro dans le libellé, sinon montant TTC exact unique."""
    kind = "sale" if r["amount"] > 0 else "purchase"
    opens = [x for x in con.execute("SELECT * FROM invoices WHERE entity_id=? AND kind=? AND status='open'", (eid, kind)) if x["id"] not in exclude]
    lab = r["label"].upper()
    for x in opens:
        if x["number"].upper() in lab and x["ttc"] == abs(r["amount"]):
            return x
    same = [x for x in opens if x["ttc"] == abs(r["amount"]) and x["date"] <= r["date"]]
    return same[0] if len(same) == 1 else None

def validate(con, eid, tx_id, account=None, tva_rate=None):
    explicit = account is not None   # choix explicite de l'utilisateur : on le mémorise (la validation en lot, non)
    tx = con.execute("SELECT * FROM bank_tx WHERE id=? AND entity_id=?", (tx_id, eid)).fetchone()
    if not tx:
        raise ledger.LedgerError("Transaction introuvable")
    if tx["status"] == "validated":
        return tx["entry_id"]
    account = account or tx["account"] or "471"
    rate = float(tva_rate if tva_rate is not None else (tx["tva_rate"] or 0))
    ent = ledger.entity(con, eid)
    if ent["kind"] == "particulier" or ent["tva_regime"] == "franchise" or account[0] not in "267":
        rate = 0.0
    amt = abs(tx["amount"]); ht = round(amt / (1 + rate / 100)); tva = amt - ht
    if tx["amount"] < 0:   # dépense
        lines = [{"account": account, "debit": ht}, {"account": "512", "credit": amt}]
        if tva:
            lines.insert(1, {"account": "44566", "debit": tva, "rate": rate, "base": ht})
    else:                  # recette
        lines = [{"account": "512", "debit": amt}, {"account": account, "credit": ht}]
        if tva:
            lines.append({"account": "44571", "credit": tva, "rate": rate, "base": ht})
    en = ledger.post_entry(con, eid, tx["date"], "BQ", tx["label"], lines, ref=f"BQ{tx_id}", source="bank")
    con.execute("UPDATE bank_tx SET status='validated', account=?, tva_rate=?, entry_id=? WHERE id=?", (account, rate, en, tx_id))
    con.execute("UPDATE lines SET pointe=1 WHERE entry_id=? AND account='512'", (en,))   # issue du relevé : pointée
    if explicit and account != "471":
        _remember(con, eid, tx["label"], tx["amount"], account, rate)
    if tx["invoice_id"] and account[:3] in ("411", "401"):
        con.execute("UPDATE invoices SET status='paid', pay_entry_id=? WHERE id=?", (en, tx["invoice_id"]))
        from . import business
        business.letter_invoice(con, eid, tx["invoice_id"], en)
        business.on_invoice_paid(con, eid, tx["invoice_id"], tx["date"])
    return en

def validate_confident(con, eid, min_conf=0.8):
    ids = [r["id"] for r in con.execute("SELECT id FROM bank_tx WHERE entity_id=? AND status='pending' AND confidence>=? AND account!='471'", (eid, min_conf))]
    for i in ids:
        validate(con, eid, i)
    return {"validated": len(ids)}
