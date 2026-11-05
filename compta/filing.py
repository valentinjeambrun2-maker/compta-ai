"""Télédéclaration : préparation, contrôle et dépôt des déclarations.

Le dépôt réel auprès de la DGFiP passe par des canaux agréés :
 - Professionnels : procédure EDI (EDI-TVA, EDI-TDFC pour les liasses, EDI-Requête) via un
   partenaire EDI agréé, ou EFI (saisie dans l'espace professionnel impots.gouv.fr).
 - Particuliers : il n'existe pas d'API publique ; la déclaration se fait dans l'espace
   particulier impots.gouv.fr (le logiciel fournit les cases à reporter).
Le connecteur EDI est donc une interface à brancher sur un partenaire EDI une fois le
contrat/agrément obtenu. Sans configuration, `submit` renvoie la marche à suivre.
"""
import json, os
from . import ledger

class EDIConnector:
    def __init__(self):
        self.endpoint = os.environ.get("EDI_PARTNER_URL")
        self.token = os.environ.get("EDI_PARTNER_TOKEN")

    def configured(self):
        return bool(self.endpoint and self.token)

    def submit(self, decl_type, payload):
        if not self.configured():
            return None
        import urllib.request
        req = urllib.request.Request(self.endpoint, data=json.dumps({"type": decl_type, "payload": payload}).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

GUIDES = {
 "ir": ["Connectez-vous sur impots.gouv.fr › Espace particulier › Déclarer mes revenus.",
        "Vérifiez les montants pré-remplis (salaires, pensions) et comparez-les avec la colonne « cases » du logiciel.",
        "Reportez les cases supplémentaires (revenus fonciers, micro, dons, emploi à domicile…).",
        "Comparez l'estimation affichée par impots.gouv.fr à celle du logiciel : un écart signale une case oubliée.",
        "Signez la déclaration et conservez l'accusé de réception (le joindre ici dans le dossier)."],
 "tva": ["Professionnels : espace professionnel impots.gouv.fr › Déclarer › TVA (EFI), ou via votre partenaire EDI.",
         "Reportez les lignes CA3 calculées (08, 9B, 09, 16, 19, 23, 25/28, 32).",
         "Validez le télépaiement du montant de la ligne 32 depuis le compte bancaire professionnel.",
         "Revenez ici et enregistrez la liquidation de TVA (écriture 44571/44566 → 44551)."],
 "is": ["Liasse fiscale (2065 + 2033 ou 2050) à déposer en EDI-TDFC via un partenaire ou en EFI.",
        "Relevé de solde IS (2572) et acomptes trimestriels (2571) sur l'espace professionnel."],
}

def validate_decl(decl_type, data):
    errs = []
    if decl_type == "ir":
        c = data.get("calcul", {})
        if not c.get("cases_2042"):
            errs.append("Aucune case renseignée.")
        if c.get("revenu_net_imposable", 0) < 0:
            errs.append("Revenu net imposable négatif.")
    if decl_type == "tva":
        if data.get("a_payer", 0) and data.get("credit", 0):
            errs.append("Montant à payer et crédit simultanés.")
    return errs

def save_and_submit(con, eid, decl_type, period, data, submit=False):
    errs = validate_decl(decl_type, data)
    status = "erreurs" if errs else "prete"
    did = con.execute("INSERT INTO declarations(entity_id,type,period,data,status) VALUES(?,?,?,?,?)",
                      (eid, decl_type, period, json.dumps(data, ensure_ascii=False), status)).lastrowid
    out = {"id": did, "status": status, "erreurs": errs, "guide": GUIDES.get(decl_type, [])}
    if submit and not errs:
        edi = EDIConnector()
        if decl_type in ("tva", "is") and edi.configured():
            out["accuse"] = edi.submit(decl_type, data)
            con.execute("UPDATE declarations SET status='deposee' WHERE id=?", (did,))
            out["status"] = "deposee"
        else:
            out["depot"] = ("Dépôt automatique indisponible : " +
                            ("aucun partenaire EDI configuré (EDI_PARTNER_URL / EDI_PARTNER_TOKEN)." if decl_type != "ir"
                             else "la DGFiP ne propose pas d'API de dépôt pour les particuliers.") +
                            " Suivez le guide pas-à-pas ci-dessous : toutes les valeurs sont prêtes à reporter.")
    return out

def mark_filed(con, eid, did):
    con.execute("UPDATE declarations SET status='deposee' WHERE id=? AND entity_id=?", (did, eid))
