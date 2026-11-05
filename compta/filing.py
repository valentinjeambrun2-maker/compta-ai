"""Télédéclaration : préparation, contrôle et dépôt des déclarations.

Le dépôt réel auprès de la DGFiP passe par des canaux agréés :
 - Professionnels : procédure EDI (EDI-TVA, EDI-TDFC pour les liasses, EDI-Requête) via un
   partenaire EDI agréé, ou EFI (saisie dans l'espace professionnel impots.gouv.fr).
 - Particuliers : il n'existe pas d'API publique ; la déclaration se fait dans l'espace
   particulier impots.gouv.fr (le logiciel fournit les cases à reporter).
Le connecteur EDI est donc une interface à brancher sur un partenaire EDI une fois le
contrat/agrément obtenu. Sans configuration, `submit` renvoie la marche à suivre.
"""
import json
from . import ledger, edi

GUIDES = {
 "ir_edi": ["Déclaration transmise par votre tiers déclarant (expert-comptable, avocat ou OGA) via la procédure EDI-IR.",
            "Un mandat écrit doit l'autoriser à déclarer pour vous ; l'accusé de réception DGFiP est archivé dans l'historique."],
 "ir": ["Connectez-vous sur impots.gouv.fr › Espace particulier › Déclarer mes revenus.",
        "Vérifiez les montants pré-remplis (salaires, pensions) et comparez-les avec la colonne « cases » du logiciel.",
        "Reportez les cases supplémentaires (revenus fonciers, micro, dons, emploi à domicile…).",
        "Comparez l'estimation affichée par impots.gouv.fr à celle du logiciel : un écart signale une case oubliée.",
        "Signez la déclaration et conservez l'accusé de réception (le joindre ici dans le dossier)."],
 "tva": ["Professionnels : espace professionnel impots.gouv.fr › Déclarer › TVA (EFI), ou via votre partenaire EDI.",
         "Reportez les lignes CA3 calculées (08, 9B, 09, 16, 19, 23, 25/28, 32).",
         "Validez le télépaiement du montant de la ligne 32 depuis le compte bancaire professionnel.",
         "Revenez ici et enregistrez la liquidation de TVA (écriture 44571/44566 → 44551)."],
 "is": ["Relevé de solde IS (2572) et acomptes trimestriels (2571) : espace professionnel impots.gouv.fr ou partenaire EDI."],
 "liasse": ["Liasse 2065 + 2033 : dépôt obligatoire en EDI-TDFC via un partenaire, ou en mode EFI pour les petites entreprises.",
            "Échéance : 2e jour ouvré après le 1er mai (exercice clos au 31/12), avec un délai supplémentaire de 15 jours en ligne."],
 "dsn": ["DSN : dépôt sur net-entreprises.fr (ou via le partenaire) au plus tard le 5 ou le 15 du mois suivant selon l'effectif.",
         "Contrôlez d'abord le fichier avec DSN-Val, puis consultez les comptes rendus métier (CRM) des organismes."],
}

def validate_decl(decl_type, data):
    errs = []
    if decl_type == "ir":
        c = data.get("calcul", {})
        if not c.get("cases_2042") and not data.get("formulaires"):
            errs.append("Aucune case renseignée.")
        if c.get("revenu_net_imposable", 0) < 0:
            errs.append("Revenu net imposable négatif.")
    if decl_type == "tva":
        a_payer, credit = data.get("a_payer", 0) or 0, data.get("credit", 0) or 0
        if a_payer < 0 or credit < 0:
            errs.append("Montant de TVA négatif.")
        if a_payer and credit:
            errs.append("Montant à payer et crédit simultanés.")
        if "collectee" in data and "deductible" in data and abs((data["collectee"] - data["deductible"]) - (a_payer - credit)) > 0.02:
            errs.append("TVA nette incohérente : elle doit égaler la TVA collectée moins la TVA déductible.")
    if decl_type == "liasse" and data.get("equilibre") is False:
        errs.append("Bilan déséquilibré : la liasse ne peut pas être transmise.")
    return errs

FINAL = ("deposee", "simulee", "transmise")

def latest(con, eid, decl_type, period):
    """Déclaration d'une période : une déclaration déposée l'emporte toujours sur un brouillon (bases avec doublons)."""
    return con.execute("""SELECT id, status FROM declarations WHERE entity_id=? AND type=? AND period=?
                          ORDER BY CASE WHEN status IN ('deposee','simulee','transmise') THEN 0 ELSE 1 END, id DESC LIMIT 1""",
                       (eid, decl_type, period)).fetchone()

def save_and_submit(con, eid, decl_type, period, data, submit=False):
    """Un brouillon par type et période, mis à jour sur place. Une déclaration déposée n'est jamais rouverte ni
    retransmise : la consulter renvoie son état sans rien enregistrer."""
    prev = latest(con, eid, decl_type, period)
    if prev and prev["status"] in FINAL:
        if submit:
            raise ledger.LedgerError("Cette déclaration est déjà déposée ou transmise : elle ne peut pas être retransmise.")
        return {"id": prev["id"], "status": prev["status"], "erreurs": [], "guide": GUIDES.get(decl_type, []), "deja_depose": True}
    errs = validate_decl(decl_type, data)
    status = "erreurs" if errs else "prete"
    payload = json.dumps(data, ensure_ascii=False)
    if prev:
        did = prev["id"]
        con.execute("UPDATE declarations SET data=?, status=? WHERE id=?", (payload, status, did))
    else:
        did = con.execute("INSERT INTO declarations(entity_id,type,period,data,status) VALUES(?,?,?,?,?)",
                          (eid, decl_type, period, payload, status)).lastrowid
    out = {"id": did, "status": status, "erreurs": errs, "guide": GUIDES.get(decl_type, [])}
    if submit and not errs:
        res = edi.submit(con, eid, decl_type, period, data, did) if decl_type in edi.FORMS else None
        if res:
            out["edi"] = res
            st = edi.declaration_status(res, edi.config(con, eid)["mode"])
            con.execute("UPDATE declarations SET status=? WHERE id=?", (st, did))
            out["status"] = st
        else:
            out["depot"] = ("Dépôt automatique indisponible : " +
                            ("aucun partenaire EDI configuré (onglet Paramètres)." if decl_type != "ir"
                             else "la DGFiP ne propose pas d'API de dépôt pour les particuliers.") +
                            " Suivez le guide pas-à-pas ci-dessous : toutes les valeurs sont prêtes à reporter.")
    return out

def mark_filed(con, eid, did):
    con.execute("UPDATE declarations SET status='deposee' WHERE id=? AND entity_id=?", (did, eid))
