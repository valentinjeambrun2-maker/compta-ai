"""Devis, relances clients par e-mail."""
import json, datetime as dt, smtplib, ssl, html
from email.message import EmailMessage
from . import ledger, business, db

E = ledger.euros

# ---------------- Devis ----------------
def _totals(lines, franchise=False):
    out, ht, tva = [], 0, 0
    for l in lines:
        rate = 0.0 if franchise else float(l.get("tva_rate", 20))
        h = round(float(l.get("qty", 1)) * ledger.cents(l.get("unit_price", 0)))
        out.append({"label": l.get("label", ""), "qty": float(l.get("qty", 1)), "unit_price": float(l.get("unit_price", 0)), "tva_rate": rate, "ht": h})
        ht += h; tva += round(h * rate / 100)
    return out, ht, tva

def create_quote(con, eid, party, date, lines, email=None, validity_days=30):
    if not lines:
        raise ledger.LedgerError("Le devis doit comporter au moins une ligne")
    ent = ledger.entity(con, eid)
    out, ht, tva = _totals(lines, ent["tva_regime"] == "franchise")
    if ht <= 0:
        raise ledger.LedgerError("Montant HT nul")
    n = con.execute("SELECT COUNT(*) FROM quotes WHERE entity_id=? AND substr(date,1,4)=?", (eid, date[:4])).fetchone()[0]
    number = f"DE-{date[:4]}-{n + 1:04d}"
    valid = (dt.date.fromisoformat(date) + dt.timedelta(days=int(validity_days))).isoformat()
    return con.execute("INSERT INTO quotes(entity_id,number,date,valid_until,party,email,lines,ht,tva,ttc) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (eid, number, date, valid, party, email, json.dumps(out), ht, tva, ht + tva)).lastrowid

def set_quote_status(con, eid, qid, status):
    if status not in ("brouillon", "envoye", "accepte", "refuse"):
        raise ledger.LedgerError("Statut de devis invalide")
    con.execute("UPDATE quotes SET status=? WHERE id=? AND entity_id=? AND status!='facture'", (status, qid, eid))

def quote_to_invoice(con, eid, qid, date=None):
    q = con.execute("SELECT * FROM quotes WHERE id=? AND entity_id=?", (qid, eid)).fetchone()
    if not q:
        raise ledger.LedgerError("Devis introuvable")
    if q["status"] == "facture":
        raise ledger.LedgerError("Ce devis a déjà été facturé")
    lines = json.loads(q["lines"])
    inv = business.create_invoice(con, eid, "sale", q["party"], date or dt.date.today().isoformat(), lines, email=q["email"], quote_id=qid)
    con.execute("UPDATE quotes SET status='facture', invoice_id=? WHERE id=?", (inv, qid))
    return inv

# ---------------- E-mail ----------------
def smtp_config(con, eid):
    g = lambda k, d=None: db.get_setting(con, eid, k, d)
    return {"host": g("smtp_host"), "port": int(g("smtp_port", 587)), "user": g("smtp_user"), "password": g("smtp_password"),
            "from": g("smtp_from") or g("smtp_user"), "security": g("smtp_security", "starttls")}

def send_mail(con, eid, to, subject, body, attachments=()):
    """Envoie par SMTP si configuré. Sinon renvoie le message prêt à copier (mode « brouillon »)."""
    cfg = smtp_config(con, eid)
    if not to:
        raise ledger.LedgerError("Adresse e-mail du destinataire manquante")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["from"] or "no-reply@localhost", to, subject
    msg.set_content(body)
    for name, mime, data in attachments:
        main, sub = mime.split("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    if not cfg["host"]:
        return {"sent": False, "channel": "brouillon", "eml": msg.as_string()[:20000],
                "message": "SMTP non configuré : e-mail préparé mais non envoyé (Paramètres › E-mail)."}
    ctx = ssl.create_default_context()
    if cfg["security"] == "ssl":
        s = smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
        if cfg["security"] == "starttls":
            s.starttls(context=ctx)
    try:
        if cfg["user"]:
            s.login(cfg["user"], cfg["password"] or "")
        s.send_message(msg)
    finally:
        s.quit()
    return {"sent": True, "channel": "smtp", "message": f"E-mail envoyé à {to}"}

# ---------------- Relances ----------------
LEVELS = {
    1: (1, "Rappel : facture {number} arrivée à échéance",
        "Bonjour,\n\nSauf erreur de notre part, la facture {number} du {date} d'un montant de {ttc} TTC, arrivée à échéance le {due}, "
        "n'a pas encore été réglée.\n\nS'il s'agit d'un oubli, nous vous remercions de bien vouloir procéder au règlement. "
        "Si votre paiement a été effectué entre-temps, merci de ne pas tenir compte de ce message.\n\nCordialement,\n{company}"),
    2: (15, "Deuxième relance : facture {number} impayée",
        "Bonjour,\n\nMalgré notre précédent rappel, la facture {number} d'un montant de {ttc} TTC (échéance du {due}) reste impayée "
        "à ce jour, soit {days} jours de retard.\n\nNous vous remercions de procéder à son règlement sous 8 jours.\n\nCordialement,\n{company}"),
    3: (30, "Mise en demeure de payer — facture {number}",
        "Madame, Monsieur,\n\nLa facture {number} du {date}, d'un montant de {ttc} TTC, échue depuis le {due}, demeure impayée malgré nos relances.\n\n"
        "Par la présente, nous vous mettons en demeure de régler cette somme sous 8 jours. À défaut, nous engagerons une procédure de recouvrement.\n\n"
        "Conformément à l'article L441-10 du Code de commerce, des pénalités de retard au taux de 3 fois le taux d'intérêt légal sont exigibles, "
        "ainsi qu'une indemnité forfaitaire pour frais de recouvrement de 40 € (art. D441-5).\n\n{company}"),
}

def _fmt_inv(con, eid, inv, today):
    ent = ledger.entity(con, eid)
    return {"number": inv["number"], "date": inv["date"], "due": inv["due"], "ttc": ledger.fr(inv["ttc"]), "company": ent["name"],
            "days": (dt.date.fromisoformat(today) - dt.date.fromisoformat(inv["due"])).days}

def due_reminders(con, eid, today=None):
    """Factures en retard et niveau de relance à envoyer."""
    today = today or dt.date.today().isoformat()
    out = []
    for inv in con.execute("SELECT * FROM invoices WHERE entity_id=? AND kind='sale' AND status='open' AND due<? ORDER BY due", (eid, today)):
        days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(inv["due"])).days
        sent = con.execute("SELECT COALESCE(MAX(level),0) FROM reminders WHERE invoice_id=? AND status IN('envoye','brouillon')", (inv["id"],)).fetchone()[0]
        nxt = next((lv for lv in (1, 2, 3) if lv > sent and days >= LEVELS[lv][0]), None)
        out.append({"invoice_id": inv["id"], "number": inv["number"], "party": inv["party"], "email": inv["email"], "ttc": E(inv["ttc"]),
                    "due": inv["due"], "retard_jours": days, "derniere_relance": sent, "prochaine": nxt})
    return out

def send_reminder(con, eid, inv_id, level=None, today=None):
    today = today or dt.date.today().isoformat()
    inv = con.execute("SELECT * FROM invoices WHERE id=? AND entity_id=? AND kind='sale'", (inv_id, eid)).fetchone()
    if not inv:
        raise ledger.LedgerError("Facture introuvable")
    if inv["status"] == "paid":
        raise ledger.LedgerError("Facture déjà réglée")
    if level is None:
        d = next((x for x in due_reminders(con, eid, today) if x["invoice_id"] == inv_id), None)
        level = (d or {}).get("prochaine") or 1
    _, subj, body = LEVELS[int(level)]
    v = _fmt_inv(con, eid, inv, today)
    atts = []
    try:
        from . import exports
        atts.append((f"{inv['number']}.pdf", "application/pdf", exports.invoice_pdf(con, eid, inv_id)))
    except Exception:
        pass
    res = send_mail(con, eid, inv["email"], subj.format(**v), body.format(**v), atts)
    con.execute("INSERT INTO reminders(entity_id,invoice_id,level,sent_at,channel,recipient,status) VALUES(?,?,?,?,?,?,?)",
                (eid, inv_id, level, today, res["channel"], inv["email"], "envoye" if res["sent"] else "brouillon"))
    res.update({"level": level, "subject": subj.format(**v), "body": body.format(**v)})
    return res

def run_auto_reminders(con, eid, today=None):
    """À lancer quotidiennement (cron) : envoie le niveau de relance dû pour chaque facture en retard ayant un e-mail."""
    done = []
    for d in due_reminders(con, eid, today):
        if d["prochaine"] and d["email"]:
            r = send_reminder(con, eid, d["invoice_id"], d["prochaine"], today)
            done.append({"facture": d["number"], "niveau": d["prochaine"], "envoye": r["sent"]})
    return done
