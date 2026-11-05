#!/usr/bin/env python3
"""ComptaIA — serveur web (stdlib uniquement). Lancer : python3 server.py [--demo] [--port 8000]"""
import json, os, re, sys, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from compta import db, ledger, bank, ai, tax, business, filing, pcg

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CON = None
ROUTES = []

def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco

E = ledger.euros
def year_of(q):
    return int(q.get("year", [dt.date.today().year])[0])

def euroize(obj, keys=("debit", "credit", "solde", "montant", "amount", "ht", "tva", "ttc", "cumul", "total_debit", "total_credit",
                       "total_charges", "total_produits", "resultat", "total_actif", "total_passif", "cost", "amortized")):
    if isinstance(obj, list):
        return [euroize(x, keys) for x in obj]
    if isinstance(obj, dict):
        return {k: (E(v) if k in keys and isinstance(v, int) else euroize(v, keys)) for k, v in obj.items()}
    return obj

# ---------- Dossiers ----------
@route("GET", "/api/entities")
def entities(c, eid, q, b):
    return [dict(r) for r in c.execute("SELECT * FROM entities ORDER BY id")]

@route("POST", "/api/entities")
def create_entity(c, eid, q, b):
    kind = b.get("kind", "entreprise")
    nid = c.execute("INSERT INTO entities(name,kind,legal_form,tva_regime,siret,address) VALUES(?,?,?,?,?,?)",
                    (b["name"], kind, b.get("legal_form", "SASU" if kind == "entreprise" else None),
                     b.get("tva_regime", "reel" if kind == "entreprise" else "aucune"), b.get("siret"), b.get("address"))).lastrowid
    pcg.seed(c, nid, kind)
    return {"id": nid}

@route("GET", "/api/dashboard")
def dashboard(c, eid, q, b):
    y = year_of(q)
    ctx = business.context(c, eid, y)
    months = []
    for m in range(1, 13):
        s, e = f"{y}-{m:02d}-01", f"{y}-{m:02d}-31"
        inc = ledger.income_statement(c, eid, s, e)
        months.append({"mois": m, "produits": E(inc["total_produits"]), "charges": E(inc["total_charges"])})
    return {"context": ctx, "mois": months, "alertes": business.audit(c, eid, y), "ia": ai.enabled()}

# ---------- Comptabilité ----------
@route("GET", "/api/accounts")
def accounts(c, eid, q, b):
    return [dict(r) for r in c.execute("SELECT code,label,tva_rate FROM accounts WHERE entity_id=? ORDER BY code", (eid,))]

@route("POST", "/api/accounts")
def add_account(c, eid, q, b):
    c.execute("INSERT INTO accounts(entity_id,code,label,tva_rate) VALUES(?,?,?,?)", (eid, b["code"], b["label"], float(b.get("tva_rate", 0))))
    return {"ok": True}

@route("GET", "/api/entries")
def entries(c, eid, q, b):
    return euroize(ledger.journal(c, eid, q.get("start", [None])[0], q.get("end", [None])[0]))

@route("POST", "/api/entries")
def post_entry(c, eid, q, b):
    lines = [{"account": l["account"], "debit": ledger.cents(l.get("debit") or 0), "credit": ledger.cents(l.get("credit") or 0)} for l in b["lines"]]
    return {"id": ledger.post_entry(c, eid, b["date"], b.get("journal", "OD"), b["label"], lines, b.get("ref"))}

@route("POST", r"/api/entries/(\d+)/delete")
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

# ---------- Banque ----------
@route("POST", "/api/bank/import")
def bank_import(c, eid, q, b):
    return bank.import_rows(c, eid, bank.parse_csv(b["csv"]))

@route("GET", "/api/bank")
def bank_list(c, eid, q, b):
    st = q.get("status", ["pending"])[0]
    return euroize([dict(r) for r in c.execute("SELECT * FROM bank_tx WHERE entity_id=? AND (?='all' OR status=?) ORDER BY date DESC,id DESC", (eid, st, st))])

@route("POST", r"/api/bank/(\d+)/validate")
def bank_validate(c, eid, q, b, tx):
    return {"entry_id": bank.validate(c, eid, int(tx), b.get("account"), b.get("tva_rate"))}

@route("POST", "/api/bank/validate-confident")
def bank_validate_all(c, eid, q, b):
    return bank.validate_confident(c, eid, float(b.get("min_conf", .8)))

# ---------- Factures ----------
@route("GET", "/api/invoices")
def invoices(c, eid, q, b):
    return euroize([{**dict(r), "lines": json.loads(r["lines"])} for r in c.execute("SELECT * FROM invoices WHERE entity_id=? ORDER BY date DESC,id DESC", (eid,))])

@route("POST", "/api/invoices")
def create_invoice(c, eid, q, b):
    return {"id": business.create_invoice(c, eid, b["kind"], b["party"], b["date"], b["lines"], b.get("number"), b.get("due"), b.get("account"))}

@route("POST", "/api/invoices/extract")
def extract(c, eid, q, b):
    return ai.extract_invoice(b["text"])

@route("POST", r"/api/invoices/(\d+)/pay")
def pay(c, eid, q, b, inv):
    return {"entry_id": business.pay_invoice(c, eid, int(inv), b.get("date"))}

@route("GET", r"/api/invoices/(\d+)/html")
def inv_html(c, eid, q, b, inv):
    return ("text/html; charset=utf-8", business.invoice_html(c, eid, int(inv)))

# ---------- Immobilisations & clôture ----------
@route("GET", "/api/assets")
def assets(c, eid, q, b):
    return euroize([dict(r) for r in c.execute("SELECT * FROM assets WHERE entity_id=?", (eid,))])

@route("POST", "/api/assets")
def add_asset(c, eid, q, b):
    return {"id": business.add_asset(c, eid, b["label"], b["date"], b["cost"], b["years"])}

@route("POST", "/api/closing")
def closing(c, eid, q, b):
    return business.close_year(c, eid, int(b["year"]), b.get("pme", True))

# ---------- Fiscalité ----------
@route("POST", "/api/tax/ir")
def ir(c, eid, q, b):
    y = int(b.get("year", dt.date.today().year - 1))
    if b.get("from_ledger"):
        return business.prepare_ir(c, eid, y, b.get("profile"))
    return {"calcul": tax.impot_revenu(b.get("profile", {}), y)}

@route("GET", "/api/tax/ca3")
def ca3(c, eid, q, b):
    return tax.ca3(c, eid, q["start"][0], q["end"][0])

@route("POST", "/api/tax/tva-settle")
def settle(c, eid, q, b):
    return {"entry_id": tax.post_tva_settlement(c, eid, b["start"], b["end"])}

@route("GET", "/api/tax/is")
def is_(c, eid, q, b):
    y = year_of(q)
    res = ledger.income_statement(c, eid, f"{y}-01-01", f"{y}-12-31")["resultat"]
    return tax.impot_societes(res / 100, q.get("pme", ["1"])[0] == "1", y)

@route("POST", "/api/tax/micro")
def micro(c, eid, q, b):
    return tax.micro_entreprise(float(b["ca"]), b.get("activite", "bnc"), bool(b.get("vl")))

@route("POST", "/api/declarations")
def declare(c, eid, q, b):
    return filing.save_and_submit(c, eid, b["type"], b["period"], b["data"], b.get("submit", False))

@route("GET", "/api/declarations")
def declarations(c, eid, q, b):
    return [{**dict(r), "data": json.loads(r["data"])} for r in c.execute("SELECT * FROM declarations WHERE entity_id=? ORDER BY id DESC", (eid,))]

@route("POST", r"/api/declarations/(\d+)/filed")
def filed(c, eid, q, b, did):
    filing.mark_filed(c, eid, int(did))
    return {"ok": True}

# ---------- IA, audit, exports ----------
@route("POST", "/api/assistant")
def assistant(c, eid, q, b):
    y = int(b.get("year", dt.date.today().year))
    return ai.assistant(b["question"], business.context(c, eid, y))

@route("GET", "/api/audit")
def audit(c, eid, q, b):
    return business.audit(c, eid, year_of(q))

@route("GET", "/api/export/fec")
def fec(c, eid, q, b):
    return ("text/plain; charset=utf-8", ledger.fec(c, eid, year_of(q)))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        u = urlparse(self.path)
        if method == "GET" and not u.path.startswith("/api/"):
            p = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = os.path.realpath(os.path.join(STATIC, p))
            if not f.startswith(STATIC) or not os.path.isfile(f):
                return self._send(404, {"error": "introuvable"})
            ct = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
            return self._send(200, open(f, "rb").read(), ct)
        q = parse_qs(u.query)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            eid = int(self.headers.get("X-Entity") or q.get("entity", [0])[0] or 0)
            for m, rx, fn in ROUTES:
                mt = rx.match(u.path)
                if m == method and mt:
                    with db.LOCK:
                        try:
                            res = fn(CON, eid, q, body, *mt.groups())
                            CON.commit()
                        except Exception:
                            CON.rollback()
                            raise
                    if isinstance(res, tuple):
                        return self._send(200, res[1], res[0])
                    return self._send(200, res)
            self._send(404, {"error": "route inconnue"})
        except ledger.LedgerError as e:
            self._send(400, {"error": str(e)})
        except (KeyError, ValueError, TypeError) as e:
            self._send(400, {"error": f"Requête invalide : {e}"})
        except Exception as e:
            self._send(500, {"error": f"Erreur interne : {e}"})

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
    print(f"ComptaIA sur http://{host}:{port}  —  IA : {'Claude (' + ai.MODEL + ')' if ai.enabled() else 'règles locales (définir ANTHROPIC_API_KEY)'}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == "__main__":
    main()
