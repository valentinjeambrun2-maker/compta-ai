#!/usr/bin/env python3
"""ComptaIA — serveur web (bibliothèque standard uniquement).

    python3 server.py [--demo] [--port 8000]

Variables : HOST (127.0.0.1), PORT, COMPTA_DB, ANTHROPIC_API_KEY, COMPTA_SECURE_COOKIE=1 derrière HTTPS.
"""
import base64, json, os, re, sys, threading, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs
from compta import (db, ledger, bank, ai, tax, business, filing, pcg, auth, documents, payroll, liasse, foncier,
                    edi, sales, expenses, exports)

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CON = None
ROUTES = []
REQ = threading.local()
MAX_BODY = 25 * 1024 * 1024
E = ledger.euros

class Response:
    def __init__(self, body, ctype="application/json; charset=utf-8", headers=None, filename=None):
        self.body, self.ctype, self.headers = body, ctype, dict(headers or {})
        if filename:
            self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'

def route(method, pattern, level="lecture"):
    """level : public | user | lecture | ecriture | membres."""
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, level))
        return fn
    return deco

def year_of(q):
    return int(q.get("year", [dt.date.today().year])[0])

def qv(q, k, d=None):
    return q.get(k, [d])[0]

MONEY_KEYS = ("debit", "credit", "solde", "montant", "amount", "ht", "tva", "ttc", "cumul", "total_debit", "total_credit",
              "total_charges", "total_produits", "resultat", "total_actif", "total_passif", "cost", "amortized", "brut", "mutuelle")

def euroize(obj):
    if isinstance(obj, list):
        return [euroize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: (E(v) if k in MONEY_KEYS and isinstance(v, int) else euroize(v)) for k, v in obj.items()}
    return obj

def b64(b):
    try:
        return base64.b64decode(b.split(",")[-1])
    except Exception:
        raise ledger.LedgerError("Fichier illisible (base64 attendu)")

def pdf(data, name):
    return Response(data, "application/pdf", filename=name)

def xl(data, name):
    return Response(data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=name)

# ======================= Authentification =======================
@route("GET", "/api/auth/state", "public")
def auth_state(c, eid, q, b):
    u = REQ.user
    return {"setup_needed": auth.needs_setup(c), "user": auth.public_user(u) if u else None, "ia": ai.enabled()}

def _session_response(tok, user):
    secure = "; Secure" if os.environ.get("COMPTA_SECURE_COOKIE") == "1" else ""
    return Response(json.dumps({"user": user}), headers={"Set-Cookie": f"session={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={7 * 86400}{secure}"})

@route("POST", "/api/auth/setup", "public")
def auth_setup(c, eid, q, b):
    auth.setup(c, b.get("email"), b.get("name"), b.get("password"))
    return _session_response(*auth.login(c, b.get("email"), b.get("password")))

@route("POST", "/api/auth/login", "public")
def auth_login(c, eid, q, b):
    return _session_response(*auth.login(c, b.get("email"), b.get("password")))

@route("POST", "/api/auth/logout", "user")
def auth_logout(c, eid, q, b):
    auth.logout(c, REQ.token)
    return Response(json.dumps({"ok": True}), headers={"Set-Cookie": "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})

@route("POST", "/api/auth/password", "user")
def auth_password(c, eid, q, b):
    auth.change_password(c, REQ.user["id"], b.get("old"), b.get("new"))
    return {"ok": True, "message": "Mot de passe modifié : reconnectez-vous."}

# ======================= Dossiers, paramètres, membres =======================
@route("GET", "/api/entities", "user")
def entities(c, eid, q, b):
    return auth.entities_for(c, REQ.user)

@route("POST", "/api/entities", "user")
def create_entity(c, eid, q, b):
    kind = b.get("kind", "entreprise")
    if kind not in ("entreprise", "particulier"):
        raise ledger.LedgerError("Type de dossier invalide")
    nid = c.execute("INSERT INTO entities(name,kind,legal_form,tva_regime,siret,address,email,tva_exigibilite) VALUES(?,?,?,?,?,?,?,?)",
                    (b.get("name") or "Nouveau dossier", kind, b.get("legal_form", "SASU" if kind == "entreprise" else None),
                     b.get("tva_regime", "reel" if kind == "entreprise" else "aucune"), b.get("siret"), b.get("address"), b.get("email"),
                     b.get("tva_exigibilite", "debits"))).lastrowid
    pcg.seed(c, nid, kind)
    c.execute("INSERT INTO memberships(user_id,entity_id,role) VALUES(?,?,'proprietaire')", (REQ.user["id"], nid))
    auth.log(c, REQ.user["id"], nid, "Création du dossier", b.get("name", ""))
    return {"id": nid}

ENTITY_FIELDS = ("name", "legal_form", "tva_regime", "tva_exigibilite", "siret", "address", "email")
SETTING_KEYS = ("effectif", "atmp", "edi_mode", "edi_url", "edi_token", "edi_partenaire", "edi_test",
                "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_security", "relances_auto")
SECRET_KEYS = ("edi_token", "smtp_password")

@route("GET", "/api/settings")
def get_settings(c, eid, q, b):
    s = {k: db.get_setting(c, eid, k) for k in SETTING_KEYS}
    for k in SECRET_KEYS:
        s[k] = "••••••••" if s[k] else ""
    return {"entity": ledger.entity(c, eid), "settings": s, "role": auth.role(c, REQ.user, eid)}

@route("POST", "/api/settings", "ecriture")
def set_settings(c, eid, q, b):
    ent = b.get("entity") or {}
    if ent.get("tva_regime") and ent["tva_regime"] not in ("reel", "franchise", "aucune"):
        raise ledger.LedgerError("Régime de TVA invalide")
    if ent.get("tva_exigibilite") and ent["tva_exigibilite"] not in ("debits", "encaissements"):
        raise ledger.LedgerError("Exigibilité de TVA invalide")
    for k in ENTITY_FIELDS:
        if k in ent:
            c.execute(f"UPDATE entities SET {k}=? WHERE id=?", (ent[k], eid))
    for k, v in (b.get("settings") or {}).items():
        if k in SETTING_KEYS and not (k in SECRET_KEYS and v == "••••••••"):
            if k == "edi_mode" and v not in ("off", "sandbox", "http"):
                raise ledger.LedgerError("Mode EDI invalide")
            db.set_setting(c, eid, k, v)
    return {"ok": True}

@route("GET", "/api/members")
def members(c, eid, q, b):
    return auth.members(c, eid)

@route("POST", "/api/members", "membres")
def add_member(c, eid, q, b):
    r = auth.add_member(c, eid, b.get("email"), b.get("role"), b.get("name"))
    if r["mot_de_passe_provisoire"]:
        ent = ledger.entity(c, eid)
        try:
            m = sales.send_mail(c, eid, r["email"], f"Invitation au dossier {ent['name']} sur ComptaIA",
                                f"Bonjour,\n\n{REQ.user['name']} vous invite à rejoindre le dossier « {ent['name']} » sur ComptaIA (rôle : {r['role']}).\n\n"
                                f"Identifiant : {r['email']}\nMot de passe provisoire : {r['mot_de_passe_provisoire']}\n\n"
                                "Changez-le dès votre première connexion.\n")
            r["email_envoye"] = m["sent"]
        except Exception as e:
            r["email_envoye"] = False
    return r

@route(r"POST", r"/api/members/(\d+)/delete", "membres")
def remove_member(c, eid, q, b, uid):
    auth.remove_member(c, eid, int(uid), REQ.user["id"])
    return {"ok": True}

@route("GET", "/api/audit-log")
def audit_log(c, eid, q, b):
    return auth.audit_trail(c, eid)

# ======================= Tableau de bord & comptabilité =======================
@route("GET", "/api/dashboard")
def dashboard(c, eid, q, b):
    y = year_of(q)
    ctx = business.context(c, eid, y)
    months = []
    for m in range(1, 13):
        inc = ledger.income_statement(c, eid, f"{y}-{m:02d}-01", f"{y}-{m:02d}-31")
        months.append({"mois": m, "produits": E(inc["total_produits"]), "charges": E(inc["total_charges"])})
    return {"context": ctx, "mois": months, "alertes": business.audit(c, eid, y), "ia": ai.enabled(), "role": auth.role(c, REQ.user, eid)}

@route("GET", "/api/accounts")
def accounts(c, eid, q, b):
    return [dict(r) for r in c.execute("SELECT code,label,tva_rate FROM accounts WHERE entity_id=? ORDER BY code", (eid,))]

@route("POST", "/api/accounts", "ecriture")
def add_account(c, eid, q, b):
    c.execute("INSERT INTO accounts(entity_id,code,label,tva_rate) VALUES(?,?,?,?)", (eid, b["code"], b["label"], float(b.get("tva_rate", 0))))
    return {"ok": True}

@route("GET", "/api/entries")
def entries(c, eid, q, b):
    return euroize(ledger.journal(c, eid, qv(q, "start"), qv(q, "end")))

@route("POST", "/api/entries", "ecriture")
def post_entry(c, eid, q, b):
    lines = [{"account": l["account"], "debit": ledger.cents(l.get("debit") or 0), "credit": ledger.cents(l.get("credit") or 0)} for l in b["lines"]]
    return {"id": ledger.post_entry(c, eid, b["date"], b.get("journal", "OD"), b["label"], lines, b.get("ref"))}

@route("POST", r"/api/entries/(\d+)/delete", "ecriture")
def del_entry(c, eid, q, b, en):
    row = c.execute("SELECT date FROM entries WHERE id=? AND entity_id=?", (en, eid)).fetchone()
    ent = ledger.entity(c, eid)
    if not row:
        raise ledger.LedgerError("Écriture introuvable")
    if ent["closed_until"] and row["date"] <= ent["closed_until"]:
        raise ledger.LedgerError("Écriture d'une période clôturée : passez une écriture d'extourne")
    c.execute("DELETE FROM entries WHERE id=?", (en,))
    c.execute("UPDATE bank_tx SET status='pending', entry_id=NULL WHERE entry_id=?", (en,))
    return {"ok": True}

@route("GET", "/api/reports/(balance|bilan|resultat|grand-livre)")
def reports(c, eid, q, b, kind):
    y = year_of(q)
    s, e = f"{y}-01-01", f"{y}-12-31"
    if kind == "balance":
        return euroize(ledger.trial_balance(c, eid, s, e))
    if kind == "bilan":
        return euroize(ledger.balance_sheet(c, eid, e))
    if kind == "resultat":
        return euroize(ledger.income_statement(c, eid, s, e))
    return euroize(ledger.grand_livre(c, eid, q["account"][0], s, e))

# ======================= Banque =======================
@route("POST", "/api/bank/import", "ecriture")
def bank_import(c, eid, q, b):
    return bank.import_rows(c, eid, bank.parse_csv(b["csv"]))

@route("GET", "/api/bank")
def bank_list(c, eid, q, b):
    st = qv(q, "status", "pending")
    return euroize([dict(r) for r in c.execute("SELECT * FROM bank_tx WHERE entity_id=? AND (?='all' OR status=?) ORDER BY date DESC,id DESC", (eid, st, st))])

@route("POST", r"/api/bank/(\d+)/validate", "ecriture")
def bank_validate(c, eid, q, b, tx):
    return {"entry_id": bank.validate(c, eid, int(tx), b.get("account"), b.get("tva_rate"))}

@route("POST", "/api/bank/validate-confident", "ecriture")
def bank_validate_all(c, eid, q, b):
    return bank.validate_confident(c, eid, float(b.get("min_conf", .8)))

# ======================= Documents (PDF / photo) =======================
@route("POST", "/api/documents/read", "ecriture")
def read_doc(c, eid, q, b):
    try:
        return documents.read_document(b64(b["data"]), b.get("mime"), b.get("filename", ""))
    except documents.DocumentError as e:
        raise ledger.LedgerError(str(e))

# ======================= Factures, devis, relances =======================
@route("GET", "/api/invoices")
def invoices(c, eid, q, b):
    return euroize([{**dict(r), "lines": json.loads(r["lines"])} for r in c.execute("SELECT * FROM invoices WHERE entity_id=? ORDER BY date DESC,id DESC", (eid,))])

@route("POST", "/api/invoices", "ecriture")
def create_invoice(c, eid, q, b):
    return {"id": business.create_invoice(c, eid, b["kind"], b["party"], b["date"], b["lines"], b.get("number"), b.get("due"),
                                          b.get("account"), b.get("nature") or "services", b.get("email"))}

@route("POST", "/api/invoices/extract", "ecriture")
def extract(c, eid, q, b):
    return ai.extract_invoice(b["text"])

@route("POST", r"/api/invoices/(\d+)/pay", "ecriture")
def pay(c, eid, q, b, inv):
    return {"entry_id": business.pay_invoice(c, eid, int(inv), b.get("date"))}

@route("GET", r"/api/invoices/(\d+)/pdf")
def inv_pdf(c, eid, q, b, inv):
    n = c.execute("SELECT number FROM invoices WHERE id=? AND entity_id=?", (inv, eid)).fetchone()
    return pdf(exports.invoice_pdf(c, eid, int(inv)), f"{n[0] if n else 'facture'}.pdf")

@route("GET", "/api/quotes")
def quotes(c, eid, q, b):
    return euroize([{**dict(r), "lines": json.loads(r["lines"])} for r in c.execute("SELECT * FROM quotes WHERE entity_id=? ORDER BY date DESC,id DESC", (eid,))])

@route("POST", "/api/quotes", "ecriture")
def create_quote(c, eid, q, b):
    return {"id": sales.create_quote(c, eid, b["party"], b["date"], b["lines"], b.get("email"), b.get("validity_days", 30))}

@route("POST", r"/api/quotes/(\d+)/status", "ecriture")
def quote_status(c, eid, q, b, qid):
    sales.set_quote_status(c, eid, int(qid), b["status"])
    return {"ok": True}

@route("POST", r"/api/quotes/(\d+)/invoice", "ecriture")
def quote_invoice(c, eid, q, b, qid):
    return {"invoice_id": sales.quote_to_invoice(c, eid, int(qid), b.get("date"))}

@route("GET", r"/api/quotes/(\d+)/pdf")
def quote_pdf(c, eid, q, b, qid):
    return pdf(exports.quote_pdf(c, eid, int(qid)), f"devis-{qid}.pdf")

@route("POST", r"/api/quotes/(\d+)/send", "ecriture")
def quote_send(c, eid, q, b, qid):
    r = c.execute("SELECT * FROM quotes WHERE id=? AND entity_id=?", (qid, eid)).fetchone()
    if not r:
        raise ledger.LedgerError("Devis introuvable")
    ent = ledger.entity(c, eid)
    res = sales.send_mail(c, eid, b.get("email") or r["email"], f"Devis {r['number']} — {ent['name']}",
                          f"Bonjour,\n\nVeuillez trouver ci-joint notre devis {r['number']} d'un montant de {ledger.fr(r['ttc'])} TTC, "
                          f"valable jusqu'au {r['valid_until']}.\n\nNous restons à votre disposition.\n\nCordialement,\n{ent['name']}",
                          [(f"{r['number']}.pdf", "application/pdf", exports.quote_pdf(c, eid, int(qid)))])
    if res["sent"]:
        sales.set_quote_status(c, eid, int(qid), "envoye")
    return res

@route("GET", "/api/reminders")
def reminders(c, eid, q, b):
    return sales.due_reminders(c, eid)

@route("POST", r"/api/reminders/(\d+)/send", "ecriture")
def reminder_send(c, eid, q, b, inv):
    if b.get("email"):
        c.execute("UPDATE invoices SET email=? WHERE id=? AND entity_id=?", (b["email"], inv, eid))
    return sales.send_reminder(c, eid, int(inv), b.get("level"))

@route("POST", "/api/reminders/auto", "ecriture")
def reminders_auto(c, eid, q, b):
    return sales.run_auto_reminders(c, eid)

# ======================= Notes de frais =======================
@route("GET", "/api/expenses")
def expense_list(c, eid, q, b):
    return euroize([{k: r[k] for k in r.keys() if k != "file_data"} | {"has_file": r["file_data"] is not None}
                    for r in c.execute("SELECT * FROM expenses WHERE entity_id=? ORDER BY date DESC,id DESC", (eid,))])

@route("POST", "/api/expenses", "ecriture")
def expense_create(c, eid, q, b):
    data = b64(b["file"]["data"]) if b.get("file") else None
    return {"id": expenses.create(c, eid, b["date"], b.get("person"), b.get("label"), b.get("category", "autre"), b.get("ttc"), b.get("tva_rate"),
                                  b.get("beneficiaire", "dirigeant"), b.get("km"), b.get("cv"),
                                  (b.get("file") or {}).get("name"), (b.get("file") or {}).get("mime"), data)}

@route("POST", "/api/expenses/receipt", "ecriture")
def expense_receipt(c, eid, q, b):
    try:
        return expenses.from_receipt(b64(b["data"]), b.get("mime"))
    except documents.DocumentError as e:
        raise ledger.LedgerError(str(e))

@route("POST", r"/api/expenses/(\d+)/validate", "ecriture")
def expense_validate(c, eid, q, b, x):
    return {"entry_id": expenses.validate(c, eid, int(x))}

@route("POST", "/api/expenses/reimburse", "ecriture")
def expense_reimburse(c, eid, q, b):
    return expenses.reimburse(c, eid, [int(i) for i in b["ids"]], b.get("date") or dt.date.today().isoformat())

@route("GET", r"/api/expenses/(\d+)/file")
def expense_file(c, eid, q, b, x):
    r = c.execute("SELECT file_name, file_mime, file_data FROM expenses WHERE id=? AND entity_id=?", (x, eid)).fetchone()
    if not r or r["file_data"] is None:
        raise ledger.LedgerError("Aucun justificatif")
    mime = r["file_mime"] if r["file_mime"] in ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif") else "application/octet-stream"
    return Response(r["file_data"], mime, filename=re.sub(r"[^\w.\-]", "_", r["file_name"] or "justificatif"))

# ======================= Paie =======================
@route("GET", "/api/employees")
def employees(c, eid, q, b):
    return euroize([dict(r) for r in c.execute("SELECT * FROM employees WHERE entity_id=? ORDER BY actif DESC, nom", (eid,))])

EMP_FIELDS = ("nom", "prenom", "nir", "naissance", "adresse", "emploi", "statut", "contrat", "date_entree", "date_sortie", "heures", "taux_pas", "actif")

@route("POST", "/api/employees", "ecriture")
def employee_save(c, eid, q, b):
    vals = {k: b.get(k) for k in EMP_FIELDS if k in b}
    for k in ("taux_pas",):
        if vals.get(k) == "":
            vals[k] = None
    vals["brut"] = ledger.cents(b.get("brut") or 0)
    vals["mutuelle"] = ledger.cents(b.get("mutuelle") or 0)
    if b.get("id"):
        sets = ", ".join(f"{k}=?" for k in vals)
        c.execute(f"UPDATE employees SET {sets} WHERE id=? AND entity_id=?", (*vals.values(), b["id"], eid))
        return {"id": b["id"]}
    cols = ", ".join(vals)
    return {"id": c.execute(f"INSERT INTO employees(entity_id, {cols}) VALUES(?{', ?' * len(vals)})", (eid, *vals.values())).lastrowid}

@route("POST", "/api/payroll/simulate", "lecture")
def payroll_sim(c, eid, q, b):
    return payroll.compute(b, b.get("period") or dt.date.today().strftime("%Y-%m"), int(db.get_setting(c, eid, "effectif", 1) or 1))

@route("POST", "/api/payroll/run", "ecriture")
def payroll_run(c, eid, q, b):
    return payroll.run_payroll(c, eid, b["period"], b.get("extras"))

@route("POST", "/api/payroll/pay", "ecriture")
def payroll_pay(c, eid, q, b):
    return {"entry_id": payroll.pay_salaries(c, eid, b["period"], b.get("date") or dt.date.today().isoformat())}

@route("GET", "/api/payslips")
def payslips(c, eid, q, b):
    out = []
    for r in c.execute("SELECT p.id, p.period, p.data, e.nom, e.prenom FROM payslips p JOIN employees e ON e.id=p.employee_id WHERE p.entity_id=? ORDER BY p.period DESC, e.nom", (eid,)):
        d = json.loads(r["data"])
        out.append({"id": r["id"], "period": r["period"], "salarie": f"{r['prenom']} {r['nom']}", "brut": d["brut"], "net_a_payer": d["net_a_payer"],
                    "pas": d["pas"], "cout": d["cout_employeur"]})
    return out

@route("GET", r"/api/payslips/(\d+)/pdf")
def payslip_pdf(c, eid, q, b, sid):
    return pdf(exports.payslip_pdf(c, eid, int(sid)), f"bulletin-{sid}.pdf")

@route("GET", "/api/dsn")
def dsn(c, eid, q, b):
    d = payroll.dsn(c, eid, q["period"][0], qv(q, "test", "1") == "1")
    if qv(q, "download"):
        return Response(d["contenu"].encode("latin-1", "replace"), "text/plain; charset=iso-8859-1", filename=f"DSN-{q['period'][0]}.txt")
    return d

# ======================= Fiscalité =======================
@route("POST", "/api/tax/ir")
def ir(c, eid, q, b):
    y = int(b.get("year", dt.date.today().year - 1))
    if b.get("from_ledger"):
        return business.prepare_ir(c, eid, y, b.get("profile"))
    return {"calcul": tax.impot_revenu(b.get("profile", {}), y)}

@route("POST", "/api/tax/foncier")
def foncier_calc(c, eid, q, b):
    return foncier.compute(b.get("biens") or [], b.get("deficits_anterieurs"))

@route("GET", "/api/tax/ca3")
def ca3(c, eid, q, b):
    return tax.ca3(c, eid, q["start"][0], q["end"][0])

@route("POST", "/api/tax/tva-settle", "ecriture")
def settle(c, eid, q, b):
    return {"entry_id": tax.post_tva_settlement(c, eid, b["start"], b["end"])}

@route("GET", "/api/tax/is")
def is_(c, eid, q, b):
    y = year_of(q)
    res = ledger.income_statement(c, eid, f"{y}-01-01", f"{y}-12-31")["resultat"]
    return tax.impot_societes(res / 100, qv(q, "pme", "1") == "1", y)

@route("POST", "/api/tax/micro")
def micro(c, eid, q, b):
    return tax.micro_entreprise(float(b["ca"]), b.get("activite", "bnc"), bool(b.get("vl")))

@route("POST", "/api/liasse")
def liasse_calc(c, eid, q, b):
    return liasse.compute(c, eid, int(b.get("year", dt.date.today().year)), b.get("reintegrations"), b.get("deductions"), b.get("pme", True))

@route("POST", "/api/declarations", "ecriture")
def declare(c, eid, q, b):
    return filing.save_and_submit(c, eid, b["type"], b["period"], b["data"], b.get("submit", False))

@route("GET", "/api/declarations")
def declarations(c, eid, q, b):
    return [{**dict(r), "data": json.loads(r["data"])} for r in c.execute("SELECT * FROM declarations WHERE entity_id=? ORDER BY id DESC", (eid,))]

@route("POST", r"/api/declarations/(\d+)/filed", "ecriture")
def filed(c, eid, q, b, did):
    filing.mark_filed(c, eid, int(did))
    return {"ok": True}

@route("GET", "/api/edi/submissions")
def edi_subs(c, eid, q, b):
    return [{**dict(r), "response": json.loads(r["response"] or "{}")} for r in c.execute("SELECT * FROM edi_submissions WHERE entity_id=? ORDER BY id DESC LIMIT 100", (eid,))]

@route("POST", "/api/edi/test", "ecriture")
def edi_test(c, eid, q, b):
    return edi.test_connection(c, eid)

@route("POST", r"/api/edi/(\d+)/refresh", "ecriture")
def edi_refresh(c, eid, q, b, sid):
    try:
        return edi.refresh(c, eid, int(sid))
    except edi.EDIError as e:
        raise ledger.LedgerError(str(e))

# ======================= Immobilisations, clôture, IA, exports =======================
@route("GET", "/api/assets")
def assets(c, eid, q, b):
    return euroize([dict(r) for r in c.execute("SELECT * FROM assets WHERE entity_id=?", (eid,))])

@route("POST", "/api/assets", "ecriture")
def add_asset(c, eid, q, b):
    return {"id": business.add_asset(c, eid, b["label"], b["date"], b["cost"], b["years"])}

@route("POST", "/api/closing", "ecriture")
def closing(c, eid, q, b):
    if auth.role(c, REQ.user, eid) == "lecteur":
        raise auth.AuthError("Accès refusé")
    return business.close_year(c, eid, int(b["year"]), b.get("pme", True))

@route("POST", "/api/assistant")
def assistant(c, eid, q, b):
    return ai.assistant(b["question"], business.context(c, eid, int(b.get("year", dt.date.today().year))))

@route("GET", "/api/audit")
def audit(c, eid, q, b):
    return business.audit(c, eid, year_of(q))

@route("GET", "/api/export/fec")
def fec(c, eid, q, b):
    y = year_of(q)
    siren = (ledger.entity(c, eid).get("siret") or "000000000").replace(" ", "")[:9]
    return Response(ledger.fec(c, eid, y).encode("utf-8"), "text/plain; charset=utf-8", filename=f"{siren}FEC{y}1231.txt")

@route("GET", r"/api/export/(pdf|xlsx)/(resultat|bilan|balance|journal|factures|liasse|paie)")
def export(c, eid, q, b, fmt, kind):
    y = year_of(q)
    if fmt == "pdf":
        return pdf(exports.report_pdf(c, eid, kind, y), f"{kind}-{y}.pdf")
    return xl(exports.report_xlsx(c, eid, kind, y), f"{kind}-{y}.xlsx")

# ======================= Serveur HTTP =======================
SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                               "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; frame-src 'self' blob:; object-src 'self' blob:; frame-ancestors 'none'",
}

class Handler(BaseHTTPRequestHandler):
    server_version = "ComptaIA"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in {**SEC_HEADERS, **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        u = urlparse(self.path)
        if method == "GET" and not u.path.startswith("/api/"):
            p = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = os.path.realpath(os.path.join(STATIC, p))
            if not f.startswith(STATIC + os.sep) or not os.path.isfile(f):
                return self._send(404, {"error": "introuvable"})
            ct = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css", "png": "image/png", "svg": "image/svg+xml"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
            with open(f, "rb") as fh:
                return self._send(200, fh.read(), ct)
        q = parse_qs(u.query)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"error": "Requête trop volumineuse (25 Mo max)"})
            if method == "POST" and "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._send(415, {"error": "Content-Type application/json requis"})  # protège contre les formulaires cross-site (CSRF)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            ck = SimpleCookie(self.headers.get("Cookie") or "")
            REQ.token = ck["session"].value if "session" in ck else None
            for m, rx, fn, level in ROUTES:
                mt = rx.match(u.path)
                if m != method or not mt:
                    continue
                with db.LOCK:
                    try:
                        REQ.user = auth.user_from_token(CON, REQ.token)
                        eid = int(self.headers.get("X-Entity") or qv(q, "entity", 0) or 0)
                        if level != "public":
                            if not REQ.user:
                                return self._send(401, {"error": "Connexion requise", "auth": True})
                            if level not in ("user",):
                                auth.require(CON, REQ.user, eid, level)
                        res = fn(CON, eid, q, body, *mt.groups())
                        if method == "POST" and REQ.user and level not in ("public",):
                            auth.log(CON, REQ.user["id"], eid, f"{method} {u.path}")
                        CON.commit()
                    except Exception:
                        CON.rollback()
                        raise
                if isinstance(res, Response):
                    return self._send(200, res.body, res.ctype, res.headers)
                return self._send(200, res)
            self._send(404, {"error": "route inconnue"})
        except auth.AuthError as e:
            self._send(403, {"error": str(e)})
        except ledger.LedgerError as e:
            self._send(400, {"error": str(e)})
        except (KeyError, ValueError, TypeError) as e:
            self._send(400, {"error": f"Requête invalide : {e}"})
        except Exception as e:
            self._send(500, {"error": f"Erreur interne : {type(e).__name__}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

def main():
    global CON
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    CON = db.connect()
    if "--demo" in args and not CON.execute("SELECT COUNT(*) FROM entities").fetchone()[0]:
        import demo
        demo.load(CON)
        print("Démo : demo@comptaia.fr / demo-compta (propriétaire) · comptable@cabinet.fr / demo-compta (comptable)")
    if auth.needs_setup(CON):
        print("Premier lancement : ouvrez l'application pour créer le compte administrateur.")
    print(f"ComptaIA sur http://{host}:{port}  —  IA : {'Claude (' + ai.MODEL + ')' if ai.enabled() else 'règles locales (définir ANTHROPIC_API_KEY)'}")
    if host not in ("127.0.0.1", "localhost"):
        print("⚠ Exposé sur le réseau : placez le serveur derrière un proxy HTTPS et définissez COMPTA_SECURE_COOKIE=1.")
    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == "__main__":
    main()
