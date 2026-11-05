"""TVA internationale et régime simplifié.

Opérations gérées (facture.operation) :
  - ue_biens     : vente = livraison intracommunautaire exonérée (art. 262 ter I CGI) ; achat = acquisition
                   intracommunautaire, TVA autoliquidée (4452 / 445662) ;
  - ue_services  : vente B2B à un preneur UE, TVA due par le preneur (art. 283-2 et 259 CGI) ; achat = autoliquidation ;
  - export       : vente hors UE exonérée (art. 262 I CGI) ; achat = importation, TVA autoliquidée (depuis 2022) ;
  - btp          : sous-traitance BTP, autoliquidation par le preneur (art. 283-2 nonies CGI).
Régime réel simplifié (RSI) : déclaration annuelle CA12 et deux acomptes (55 % en juillet, 40 % en décembre),
non dus si la TVA de l'exercice précédent est inférieure à 1 000 €.
"""
import datetime as dt
from . import ledger

MENTIONS = {
    "ue_biens": "Exonération de TVA — livraison intracommunautaire, art. 262 ter I du CGI.",
    "ue_services": "Autoliquidation — TVA due par le preneur, art. 283-2 du CGI / art. 196 de la directive 2006/112/CE.",
    "export": "Exonération de TVA — exportation, art. 262 I du CGI.",
    "btp": "Autoliquidation — art. 283-2 nonies du CGI (sous-traitance BTP).",
}
SALE_ACCOUNT = {"ue_biens": "7071", "ue_services": "7061", "export": "7072", "btp": "704"}

def create_international_invoice(con, eid, kind, t, date, lines, number, due, account, nature, email, quote_id, operation):
    from . import business
    if operation not in MENTIONS:
        raise ledger.LedgerError("Type d'opération inconnu")
    if kind == "sale" and operation in ("ue_biens", "ue_services") and not t.get("tva_intra"):
        raise ledger.LedgerError("Numéro de TVA intracommunautaire du client obligatoire pour une opération intracommunautaire")
    out, ht = [], 0
    rate_auto = 20.0
    for l in lines:
        h = round(float(l.get("qty", 1)) * ledger.cents(l.get("unit_price", 0)))
        rate_auto = float(l.get("tva_rate", 20)) or 20.0
        out.append({"label": l.get("label", ""), "qty": float(l.get("qty", 1)), "unit_price": float(l.get("unit_price", 0)), "tva_rate": 0, "ht": h})
        ht += h
    if ht <= 0:
        raise ledger.LedgerError("Montant HT nul")
    if kind == "sale":
        number = business.next_number(con, eid, date[:4])
        account = account or SALE_ACCOUNT[operation]
        el = [{"account": t["account"], "debit": ht, "label": f"{number} {t['nom']}"}, {"account": account, "credit": ht, "rate": 0, "base": ht}]
        jr = "VE"
    else:
        number = number or f"ACH-{date}"
        account = account or ("607" if operation in ("ue_biens", "export") else "604")
        tva = round(ht * rate_auto / 100)
        el = [{"account": account, "debit": ht}, {"account": "445662", "debit": tva, "rate": rate_auto, "base": ht},
              {"account": "4452", "credit": tva, "rate": rate_auto, "base": ht}, {"account": t["account"], "credit": ht, "label": f"{number} {t['nom']}"}]
        jr = "AC"
    en = ledger.post_entry(con, eid, date, jr, f"Facture {number} — {t['nom']} ({operation})", el, ref=number, source="invoice")
    return business.save_invoice(con, eid, kind, number, date, due, t["nom"], ht, 0, ht, out, account, en, nature, email, quote_id, t, operation)

def international_lines(con, eid, start, end):
    """Bases des opérations exonérées / autoliquidées pour la CA3."""
    def base(acc, sign=1):
        r = con.execute("""SELECT COALESCE(SUM(l.credit-l.debit),0) FROM lines l JOIN entries e ON e.id=l.entry_id
                           WHERE e.entity_id=? AND l.account=? AND e.date BETWEEN ? AND ?""", (eid, acc, start, end)).fetchone()[0]
        return sign * r
    auto = con.execute("""SELECT COALESCE(SUM(l.base),0), COALESCE(SUM(l.credit),0) FROM lines l JOIN entries e ON e.id=l.entry_id
                          WHERE e.entity_id=? AND l.account='4452' AND e.date BETWEEN ? AND ?""", (eid, start, end)).fetchone()
    ded = con.execute("""SELECT COALESCE(SUM(l.debit-l.credit),0) FROM lines l JOIN entries e ON e.id=l.entry_id
                         WHERE e.entity_id=? AND l.account='445662' AND e.date BETWEEN ? AND ?""", (eid, start, end)).fetchone()[0]
    return {"exportations": base("7072"), "livraisons_ue": base("7071"), "prestations_ue": base("7061"),
            "acquisitions_ue_base": auto[0], "tva_autoliquidee": auto[1], "tva_deductible_autoliquidee": ded}

# ---------------- Régime simplifié : CA12 ----------------
def ca12(con, eid, year):
    from . import tax
    s, e = f"{year}-01-01", f"{year}-12-31"
    d = tax.ca3(con, eid, s, e)
    prev = tax.ca3(con, eid, f"{year - 1}-01-01", f"{year - 1}-12-31")
    acomptes = con.execute("""SELECT COALESCE(SUM(l.debit-l.credit),0) FROM lines l JOIN entries en ON en.id=l.entry_id
                              WHERE en.entity_id=? AND l.account='44581' AND en.date BETWEEN ? AND ?""", (eid, s, e)).fetchone()[0]
    net = ledger.cents(d["a_payer"]) - ledger.cents(d["credit"])
    solde = net - acomptes
    base_prev = ledger.cents(prev["a_payer"])
    sched = []
    if base_prev >= 100000:
        sched = [{"echeance": f"{year + 1}-07-15", "montant": ledger.euros(round(base_prev * .55))},
                 {"echeance": f"{year + 1}-12-15", "montant": ledger.euros(round(base_prev * .40))}]
    E = ledger.euros
    lignes = dict(d["lignes"])
    lignes.update({"Acomptes versés (44581)": E(acomptes), "Solde à payer": E(max(solde, 0)), "Crédit de TVA": E(max(-solde, 0))})
    return {"annee": year, "lignes": lignes, "tva_nette_annuelle": E(net), "acomptes_verses": E(acomptes), "solde": E(solde),
            "acomptes_annee_suivante": sched, "echeance_depot": f"{year + 1}-05-05 (2e jour ouvré suivant le 1er mai, exercice civil)",
            "note": "Acomptes de l'année suivante calculés sur la TVA nette de l'exercice précédent (base hors TVA sur immobilisations : à ajuster)."}

def pay_acompte(con, eid, date, montant_eur):
    c = ledger.cents(montant_eur)
    return ledger.post_entry(con, eid, date, "BQ", "Acompte de TVA (régime simplifié)", [{"account": "44581", "debit": c}, {"account": "512", "credit": c}], source="tva")
