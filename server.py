#!/usr/bin/env python3
"""ComptaIA — serveur web (bibliothèque standard uniquement).

    python3 server.py [--demo] [--port 8000]

Variables : HOST (127.0.0.1), PORT, COMPTA_DB, ANTHROPIC_API_KEY, COMPTA_SECURE_COOKIE=1 derrière HTTPS.
Elles peuvent aussi être placées dans un fichier `.env` à la racine du projet (ignoré par Git ; l'environnement réel prime).
"""
import base64, json, os, re, sys, threading, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs
from compta import envfile
envfile.load()  # doit précéder les imports ci-dessous : compta.ai et compta.db lisent l'environnement à l'import
from compta import (db, ledger, bank, ai, tax, business, filing, pcg, auth, documents, payroll, liasse, foncier,
                    edi, sales, expenses, exports, tiers, closing, analysis, vat, profile, tax_agent, obligations, agents)

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

def _page(q, default=200, maxi=1000):
    """Pagination : `limit` (défaut 200, max 1000) et `offset`."""
    return min(max(int(qv(q, "limit", default) or default), 1), maxi), max(int(qv(q, "offset", 0) or 0), 0)

@route("GET", "/api/entries")
def entries(c, eid, q, b):
    lim, off = _page(q)
    s, e = qv(q, "start"), qv(q, "end")
    return euroize({"items": ledger.journal(c, eid, s, e, lim, off), "nombre": ledger.journal_total(c, eid, s, e),
                    "limit": lim, "offset": off})

@route("POST", "/api/entries", "ecriture")
def post_entry(c, eid, q, b):
    lines = [{"account": l["account"], "debit": ledger.cents(l.get("debit") or 0), "credit": ledger.cents(l.get("credit") or 0)} for l in b["lines"]]
    return {"id": ledger.post_entry(c, eid, b["date"], b.get("journal", "OD"), b["label"], lines, b.get("ref"))}

@route("POST", r"/api/entries/(\d+)/cancel", "ecriture")
def cancel_entry(c, eid, q, b, en):
    """Annulation par contre-passation : l'écriture n'est jamais effacée (piste d'audit)."""
    nid = ledger.cancel_entry(c, eid, int(en))
    auth.log(c, REQ.user["id"], eid, "annulation_ecriture", f"écriture {en} annulée par la contre-passation {nid}")
    return {"ok": True, "contre_passation_id": nid}

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
                                          b.get("account"), b.get("nature") or "services", b.get("email"), operation=b.get("operation") or "france",
                                          tiers_info={k: b[k] for k in ("tva_intra", "pays", "siren") if b.get(k)})}

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
def closing_route(c, eid, q, b):
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

@route("GET", r"/api/export/(pdf|xlsx)/(resultat|bilan|balance|journal|factures|liasse|paie|sig|agee|grandlivre)")
def export(c, eid, q, b, fmt, kind):
    y = year_of(q)
    if fmt == "pdf":
        return pdf(exports.report_pdf(c, eid, kind, y), f"{kind}-{y}.pdf")
    return xl(exports.report_xlsx(c, eid, kind, y), f"{kind}-{y}.xlsx")

# ======================= Tiers et lettrage =======================
@route("GET", "/api/tiers")
def tiers_list(c, eid, q, b):
    return euroize(tiers.listing(c, eid, qv(q, "type")))

@route("POST", "/api/tiers", "ecriture")
def tiers_create(c, eid, q, b):
    t = tiers.find_or_create(c, eid, b["type"], b["nom"], **{k: b.get(k) for k in ("siren", "tva_intra", "pays", "email", "telephone", "adresse", "delai_jours", "notes")})
    return {"id": t["id"], "account": t["account"]}

@route("POST", r"/api/tiers/(\d+)", "ecriture")
def tiers_update(c, eid, q, b, tid):
    tiers.update(c, eid, int(tid), b)
    return {"ok": True}

@route("GET", r"/api/tiers/(\d+)/lines")
def tiers_lines(c, eid, q, b, tid):
    t = c.execute("SELECT * FROM tiers WHERE id=? AND entity_id=?", (tid, eid)).fetchone()
    if not t:
        raise ledger.LedgerError("Tiers introuvable")
    return {"tiers": dict(t), "lignes": euroize(tiers.open_lines(c, eid, t["account"])), "risque": tiers.risk_score(c, eid, int(tid)) if t["type"] == "client" else None}

@route("POST", "/api/lettrage", "ecriture")
def lettrage(c, eid, q, b):
    return {"code": tiers.letter(c, eid, [int(i) for i in b["line_ids"]])}

@route("POST", "/api/lettrage/auto", "ecriture")
def lettrage_auto(c, eid, q, b):
    return tiers.auto_letter(c, eid, b.get("account"))

@route("POST", "/api/lettrage/undo", "ecriture")
def lettrage_undo(c, eid, q, b):
    tiers.unletter(c, eid, b["account"], b["code"])
    return {"ok": True}

@route("GET", "/api/aged")
def aged(c, eid, q, b):
    return euroize(tiers.aged_balance(c, eid, qv(q, "type", "client")))

# ======================= Révision et clôture =======================
@route("GET", "/api/rappro")
def rappro(c, eid, q, b):
    return closing.reconciliation(c, eid, qv(q, "date", dt.date.today().isoformat()), qv(q, "solde"))

@route("POST", "/api/rappro/statement", "ecriture")
def rappro_statement(c, eid, q, b):
    closing.set_statement(c, eid, b["date"], b["solde"])
    return closing.reconciliation(c, eid, b["date"])

@route("POST", r"/api/lines/(\d+)/point", "ecriture")
def point(c, eid, q, b, lid):
    return {"pointe": closing.toggle_point(c, eid, int(lid), b.get("value"))}

@route("POST", r"/api/entries/(\d+)/reverse", "ecriture")
def reverse(c, eid, q, b, en):
    return {"entry_id": closing.reverse_entry(c, eid, int(en), b.get("date"))}

@route("GET", "/api/search")
def search_route(c, eid, q, b):
    lim, off = _page(q)
    f = (qv(q, "q"), qv(q, "account"), qv(q, "start"), qv(q, "end"), qv(q, "min"), qv(q, "max"), qv(q, "journal"))
    return euroize({"items": ledger.search(c, eid, *f, limit=lim, offset=off), "nombre": ledger.search_total(c, eid, *f),
                    "limit": lim, "offset": off})

@route("GET", "/api/regularisations/suggest")
def regul_suggest(c, eid, q, b):
    return closing.suggest_regularisations(c, eid, year_of(q))

@route("POST", "/api/regularisations", "ecriture")
def regul(c, eid, q, b):
    return closing.regularisation(c, eid, b["type"], b.get("account"), b["montant"], int(b["year"]), b.get("label", ""), b.get("tva_rate", 0), b.get("auto_reverse", True))

@route("POST", "/api/result/allocate", "ecriture")
def allocate(c, eid, q, b):
    return closing.allocate_result(c, eid, int(b["year"]), b["date"], b.get("reserve_legale"), b.get("dividendes", 0))

@route("GET", "/api/attachments")
def attachments(c, eid, q, b):
    return [dict(r) for r in c.execute("SELECT id, name, mime, entry_id, created FROM attachments WHERE entity_id=? AND (? IS NULL OR entry_id=?)", (eid, qv(q, "entry_id"), qv(q, "entry_id")))]

@route("POST", "/api/attachments", "ecriture")
def attach_route(c, eid, q, b):
    f = b["file"]
    return {"id": closing.attach(c, eid, f.get("name"), f.get("mime"), b64(f["data"]), b.get("entry_id"))}

@route("GET", r"/api/attachments/(\d+)")
def attachment(c, eid, q, b, aid):
    r = c.execute("SELECT name, mime, data FROM attachments WHERE id=? AND entity_id=?", (aid, eid)).fetchone()
    if not r:
        raise ledger.LedgerError("Pièce introuvable")
    mime = r["mime"] if r["mime"] in ("application/pdf", "image/jpeg", "image/png", "image/webp") else "application/octet-stream"
    return Response(r["data"], mime, filename=re.sub(r"[^\w.\-]", "_", r["name"] or "piece"))

# ======================= Analyse =======================
@route("GET", "/api/analysis/sig")
def a_sig(c, eid, q, b):
    r = analysis.sig(c, eid, year_of(q)); r.pop("_raw", None)
    return r

@route("GET", "/api/analysis/ratios")
def a_ratios(c, eid, q, b):
    return analysis.ratios(c, eid, year_of(q))

@route("GET", "/api/analysis/forecast")
def a_forecast(c, eid, q, b):
    return analysis.cash_forecast(c, eid, int(qv(q, "months", 12)))

@route("GET", "/api/budget")
def budget(c, eid, q, b):
    return analysis.budget_vs_actual(c, eid, year_of(q))

@route("POST", "/api/budget", "ecriture")
def budget_set(c, eid, q, b):
    analysis.set_budget(c, eid, int(b["year"]), b["account"], b["annual"])
    return {"ok": True}

# ======================= TVA simplifiée =======================
@route("GET", "/api/tax/ca12")
def ca12(c, eid, q, b):
    return vat.ca12(c, eid, year_of(q))

@route("POST", "/api/tax/acompte", "ecriture")
def acompte(c, eid, q, b):
    return {"entry_id": vat.pay_acompte(c, eid, b.get("date") or dt.date.today().isoformat(), b["montant"])}

# ======================= Profil et entretien IA =======================
def _kind(c, eid):
    return ledger.entity(c, eid)["kind"]

@route("GET", "/api/profile")
def profile_get(c, eid, q, b):
    k = _kind(c, eid)
    p, done = profile.get(c, eid)
    return {"kind": k, "termine": done, "progress": profile.progress(k, p), "question": profile.public(profile.next_question(k, p)),
            "profil": profile.summary(k, p), "echeances": profile.deadlines(k, p, int(qv(q, "year", dt.date.today().year))), "ia": ai.enabled()}

@route("POST", "/api/profile/answer", "ecriture")
def profile_answer(c, eid, q, b):
    return profile.answer(c, eid, _kind(c, eid), b.get("qid"), b.get("value"), b.get("free_text"), bool(b.get("skip")))

@route("POST", "/api/profile/edit", "ecriture")
def profile_edit(c, eid, q, b):
    k = _kind(c, eid)
    p, done = profile.get(c, eid)
    qd = profile.BY_ID.get(b["id"])
    if not qd:
        raise ledger.LedgerError("Champ inconnu")
    v = profile.parse_answer(qd, b.get("value"))
    if v is None:
        p.pop(b["id"], None)
    else:
        p[b["id"]] = v
    profile.save(c, eid, p, done)
    profile.apply(c, eid, k, p)
    return {"ok": True, "profil": profile.summary(k, p)}

@route("POST", "/api/profile/restart", "ecriture")
def profile_restart(c, eid, q, b):
    p, _ = profile.get(c, eid)
    p.pop("_skipped", None)
    profile.save(c, eid, p, False)
    return {"ok": True}

# ======================= Agent Impôts (particuliers) =======================
@route("GET", "/api/ir/declaration")
def ir_decl(c, eid, q, b):
    return tax_agent.build(c, eid, year_of(q))

@route("POST", "/api/ir/declaration")
def ir_decl_post(c, eid, q, b):
    return tax_agent.build(c, eid, int(b.get("year")), b.get("overrides"))

@route("GET", "/api/ir/documents")
def ir_docs(c, eid, q, b):
    return tax_agent.list_documents(c, eid, year_of(q))

@route("POST", "/api/ir/documents", "ecriture")
def ir_doc_add(c, eid, q, b):
    f = b["file"]
    try:
        return tax_agent.add_document(c, eid, int(b["year"]), f.get("name", "document"), f.get("mime"), b64(f["data"]), b.get("kind"), b.get("beneficiaire"))
    except documents.DocumentError as e:
        raise ledger.LedgerError(str(e))

@route("POST", r"/api/ir/documents/(\d+)/delete", "ecriture")
def ir_doc_del(c, eid, q, b, did):
    c.execute("DELETE FROM tax_documents WHERE id=? AND entity_id=?", (did, eid))
    return {"ok": True}

@route("POST", "/api/ir/review")
def ir_review(c, eid, q, b):
    d = tax_agent.build(c, eid, int(b["year"]), b.get("overrides"))
    p, _ = profile.get(c, eid)
    return {"remarques": tax_agent.ai_review(d, p), "ia": ai.enabled()}

@route("POST", "/api/ir/submit", "ecriture")
def ir_submit(c, eid, q, b):
    d = tax_agent.build(c, eid, int(b["year"]), b.get("overrides"))
    return tax_agent.submit(c, eid, int(b["year"]), d)

# ======================= Obligations de l'entreprise =======================
@route("GET", "/api/obligations")
def oblig(c, eid, q, b):
    return obligations.listing(c, eid, year_of(q))

@route("POST", "/api/obligations/run", "ecriture")
def oblig_run(c, eid, q, b):
    return obligations.run(c, eid, int(b["year"]), b.get("only_due", True))

@route("POST", "/api/obligations/file", "ecriture")
def oblig_file(c, eid, q, b):
    o = next((x for x in obligations.listing(c, eid, int(b["year"]))["obligations"] if x["type"] == b["type"] and x["periode"] == b["periode"]), None)
    if not o:
        raise ledger.LedgerError("Obligation introuvable")
    data = json.loads(json.dumps(obligations.prepare(c, eid, o), default=str))
    return {**filing.save_and_submit(c, eid, o["type"], o["periode"], data, submit=bool(b.get("submit", True))), "donnees": data}

# ======================= Agents IA =======================
@route("GET", r"/api/agents/tab/(\w+)")
def agent_tab(c, eid, q, b, tab):
    r = agents.run(c, eid, agents.for_tab(_kind(c, eid), tab), year_of(q))
    r.pop("_ctx", None)
    return r

@route("GET", r"/api/agents/(\w+)")
def agent_get(c, eid, q, b, name):
    if name not in agents.AGENTS:
        raise ledger.LedgerError("Agent inconnu")
    r = agents.run(c, eid, name, year_of(q)); r.pop("_ctx", None)
    return r

@route("POST", r"/api/agents/(\w+)/ask")
def agent_ask(c, eid, q, b, name):
    if name not in agents.AGENTS:
        raise ledger.LedgerError("Agent inconnu")
    return agents.ask(c, eid, name, int(b.get("year", dt.date.today().year)), b["question"], b.get("history"))

@route("GET", "/api/agents")
def agent_list(c, eid, q, b):
    return [{"id": k, "titre": v[0], "description": v[1]} for k, v in agents.AGENTS.items()]

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
    if envfile.LOADED:  # noms seulement, jamais les valeurs
        print("Variables lues depuis .env :", ", ".join(envfile.LOADED))
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
