"""Transmission des déclarations professionnelles via un partenaire EDI agréé DGFiP / net-entreprises.

La DGFiP n'accepte les dépôts automatisés (EDI-TVA, EDI-TDFC pour la liasse, EDI-Paiement) que par
l'intermédiaire de partenaires EDI agréés ; la DSN passe par net-entreprises.fr. Il faut donc signer
un contrat avec un partenaire (liste officielle sur impots.gouv.fr › Professionnels › « partenaires EDI »).

Trois modes, réglables par dossier (onglet Paramètres) :
  - off      : préparation seulement, l'utilisateur saisit lui-même sur impots.gouv.fr ;
  - sandbox  : simulateur local (aucun envoi réel) pour tester le parcours de bout en bout ;
  - http     : API REST du partenaire. Contrat attendu (à adapter au partenaire choisi) :
        POST {url}/declarations  {type, siren, periode, formulaire, donnees, test}
             → 200 {"ref": "...", "status": "recu|accepte|rejete", "message": "..."}
        GET  {url}/declarations/{ref} → {"ref", "status", "message", "accuse"}
        Authentification : en-tête « Authorization: Bearer <jeton> ».
"""
import json, datetime as dt, urllib.request, urllib.error
from . import db, ledger

FORMS = {"tva": "3310-CA3", "is": "2572-SD", "liasse": "2065-SD + 2033-A à G", "dsn": "DSN mensuelle (NEODeS)"}
REQUIRED = {"tva": ["lignes"], "is": ["2065"], "liasse": ["2033A_actif", "2033B", "2065"], "dsn": ["contenu"]}

class EDIError(Exception):
    pass

def config(con, eid):
    g = lambda k, d=None: db.get_setting(con, eid, k, d)
    return {"mode": g("edi_mode", "off"), "url": g("edi_url"), "token": g("edi_token"), "partenaire": g("edi_partenaire"),
            "test": g("edi_test", "1") == "1"}

def _siren(con, eid):
    s = (ledger.entity(con, eid).get("siret") or "").replace(" ", "")[:9]
    return s

def check(decl_type, data, siren):
    errs = []
    if decl_type not in FORMS:
        errs.append(f"Type de déclaration non transmissible par EDI : {decl_type}")
    for k in REQUIRED.get(decl_type, []):
        if not data.get(k):
            errs.append(f"Champ obligatoire manquant : {k}")
    if not (siren.isdigit() and len(siren) == 9):
        errs.append("SIREN absent ou invalide (renseignez le SIRET dans les paramètres du dossier).")
    return errs

class Sandbox:
    """Simule un partenaire EDI : contrôles de forme, accusé de réception fictif."""
    def submit(self, payload):
        errs = check(payload["type"], payload["donnees"], payload["siren"])
        ref = f"SBX-{payload['type'].upper()}-{dt.datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
        if errs:
            return {"ref": ref, "status": "rejete", "message": " ; ".join(errs)}
        return {"ref": ref, "status": "accepte", "message": "Simulation : déclaration conforme, aucun envoi réel effectué.",
                "accuse": {"horodatage": dt.datetime.now().isoformat(timespec="seconds"), "formulaire": payload["formulaire"]}}

    def status(self, ref):
        return {"ref": ref, "status": "accepte", "message": "Simulation"}

class HttpPartner:
    def __init__(self, url, token):
        if not url or not token:
            raise EDIError("URL et jeton du partenaire EDI requis.")
        if not url.startswith("https://"):
            raise EDIError("L'URL du partenaire doit être en HTTPS.")
        self.url, self.token = url.rstrip("/"), token

    def _call(self, method, path, body=None):
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise EDIError(f"Partenaire EDI : HTTP {e.code} — {e.read()[:300].decode('utf-8', 'replace')}")
        except urllib.error.URLError as e:
            raise EDIError(f"Partenaire EDI injoignable : {e.reason}")

    def submit(self, payload):
        return self._call("POST", "/declarations", payload)

    def status(self, ref):
        return self._call("GET", f"/declarations/{ref}")

def connector(cfg):
    if cfg["mode"] == "sandbox":
        return Sandbox()
    if cfg["mode"] == "http":
        return HttpPartner(cfg["url"], cfg["token"])
    return None

def submit(con, eid, decl_type, period, data, declaration_id=None):
    cfg = config(con, eid)
    conn = connector(cfg)
    if not conn:
        return None
    payload = {"type": decl_type, "siren": _siren(con, eid), "periode": period, "formulaire": FORMS.get(decl_type, decl_type),
               "donnees": data, "test": cfg["test"]}
    try:
        res = conn.submit(payload)
    except EDIError as e:
        res = {"ref": None, "status": "erreur", "message": str(e)}
    con.execute("INSERT INTO edi_submissions(entity_id,declaration_id,type,mode,ref,status,response) VALUES(?,?,?,?,?,?,?)",
                (eid, declaration_id, decl_type, cfg["mode"], res.get("ref"), res.get("status"), json.dumps(res, ensure_ascii=False)))
    return res

def refresh(con, eid, sub_id):
    s = con.execute("SELECT * FROM edi_submissions WHERE id=? AND entity_id=?", (sub_id, eid)).fetchone()
    if not s or not s["ref"]:
        raise EDIError("Envoi introuvable ou sans référence")
    conn = connector(config(con, eid))
    if not conn:
        raise EDIError("Aucun partenaire EDI configuré")
    res = conn.status(s["ref"])
    con.execute("UPDATE edi_submissions SET status=?, response=? WHERE id=?", (res.get("status"), json.dumps(res, ensure_ascii=False), sub_id))
    return res

def test_connection(con, eid):
    cfg = config(con, eid)
    if cfg["mode"] == "off":
        return {"ok": False, "message": "Mode EDI désactivé"}
    try:
        c = connector(cfg)
        if isinstance(c, Sandbox):
            return {"ok": True, "message": "Simulateur actif : les envois seront simulés."}
        c._call("GET", "/ping")
        return {"ok": True, "message": "Connexion au partenaire réussie."}
    except EDIError as e:
        return {"ok": False, "message": str(e)}
