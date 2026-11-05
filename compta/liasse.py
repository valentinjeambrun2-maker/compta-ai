"""Liasse fiscale du régime simplifié d'imposition (RSI) : 2033-A (bilan), 2033-B (résultat et
détermination du résultat fiscal), 2033-C (immobilisations et amortissements) et 2065 (déclaration d'IS).

⚠ Les numéros de lignes suivent les formulaires CERFA 2033 ; contrôlez-les sur le millésime de l'année.
Le dépôt se fait en EDI-TDFC via un partenaire agréé (voir compta/edi.py).
"""
from . import ledger, tax

def _bal(con, eid, end, start=None):
    return {b["account"]: b["solde"] for b in ledger.balances(con, eid, start, end)}

def _sum(bal, prefixes, sign=1, only=None):
    """Somme des soldes (débit - crédit) des comptes commençant par un des préfixes. only='D' ou 'C' : soldes débiteurs / créditeurs."""
    t = 0
    for acc, s in bal.items():
        if any(acc.startswith(p) for p in prefixes):
            if only == "D" and s <= 0 or only == "C" and s >= 0:
                continue
            t += s
    return sign * t

def compute(con, eid, year, reintegrations=None, deductions=None, pme=True):
    s, e = f"{year}-01-01", f"{year}-12-31"
    bal, res = _bal(con, eid, e), _bal(con, eid, e, s)
    E = ledger.euros
    # ---- 2033-A Bilan simplifié
    immo_corp = _sum(bal, ["21"], only="D"); amort = -_sum(bal, ["28"])
    actif = [
        ("010", "Immobilisations incorporelles", _sum(bal, ["20"], only="D")),
        ("028", "Immobilisations corporelles (brut)", immo_corp),
        ("030", "Amortissements des immobilisations corporelles", -amort),
        ("040", "Immobilisations financières", _sum(bal, ["27"], only="D")),
        ("050", "Stocks", _sum(bal, ["3"], only="D")),
        ("068", "Créances clients", _sum(bal, ["411"], only="D")),
        ("072", "Autres créances (dont TVA déductible)", _sum(bal, ["44", "455", "467", "471", "425"], only="D")),
        ("084", "Disponibilités", _sum(bal, ["512", "53"], only="D")),
        ("092", "Charges constatées d'avance", _sum(bal, ["486"], only="D")),
    ]
    resultat = -sum(v for k, v in res.items() if k[0] in "67")
    passif = [
        ("120", "Capital social ou individuel", -_sum(bal, ["101", "108"])),
        ("132", "Réserves", -_sum(bal, ["106"])),
        ("134", "Report à nouveau", -_sum(bal, ["11"])),
        ("136", "Résultat de l'exercice", resultat),
        ("156", "Emprunts et dettes assimilées (dont découverts)", -_sum(bal, ["16"]) - _sum(bal, ["512", "519"], only="C")),
        ("166", "Fournisseurs et comptes rattachés", -_sum(bal, ["401", "404"], only="C")),
        ("169", "Dettes fiscales et sociales", -_sum(bal, ["42", "43", "44"], only="C")),
        ("172", "Autres dettes", -_sum(bal, ["455", "467", "471", "411"], only="C")),
    ]
    # Résultats antérieurs non affectés (exercices précédents non clôturés en comptabilité) : rattachés au report à nouveau
    anterieur = -sum(v for k, v in _bal(con, eid, f"{year - 1}-12-31").items() if k[0] in "67")
    if anterieur:
        passif[2] = ("134", "Report à nouveau (dont résultats antérieurs)", passif[2][2] + anterieur)
    ta, tp = sum(v for _, _, v in actif), sum(v for _, _, v in passif)
    actif.append(("110", "TOTAL ACTIF", ta)); passif.append(("180", "TOTAL PASSIF", tp))
    # ---- 2033-B Compte de résultat
    P = lambda *p: -_sum(res, list(p))
    C = lambda *p: _sum(res, list(p))
    pe = [("210", "Ventes de marchandises", P("707")), ("214", "Production vendue — biens", P("701", "702", "703")),
          ("218", "Production vendue — services", P("704", "705", "706", "708")), ("230", "Autres produits d'exploitation", P("74", "75", "781"))]
    ce = [("234", "Achats de marchandises", C("607")), ("236", "Variation de stock (marchandises)", C("6037")),
          ("238", "Achats de matières premières", C("601", "602")), ("242", "Autres charges externes", C("604", "605", "606", "61", "62")),
          ("244", "Impôts, taxes et versements assimilés", C("63")), ("250", "Rémunérations du personnel", C("641", "644")),
          ("252", "Charges sociales", C("645", "646", "647")), ("254", "Dotations aux amortissements", C("681")),
          ("262", "Autres charges", C("65"))]
    tpe, tce = sum(v for *_, v in pe), sum(v for *_, v in ce)
    pf, cf, px, cx, imp = P("76", "786"), C("66", "686"), P("77", "787"), C("67", "687"), C("695", "696", "698", "699")
    compte = pe + [("232", "Total des produits d'exploitation", tpe)] + ce + [("264", "Total des charges d'exploitation", tce),
             ("270", "Résultat d'exploitation", tpe - tce), ("280", "Produits financiers", pf), ("290", "Produits exceptionnels", px),
             ("294", "Charges financières", cf), ("300", "Charges exceptionnelles", cx), ("306", "Impôt sur les bénéfices", imp),
             ("310", "Bénéfice ou perte", tpe - tce + pf + px - cf - cx - imp)]
    # ---- Résultat fiscal
    rein = {"Impôt sur les sociétés comptabilisé (non déductible)": imp}
    for k, v in (reintegrations or {}).items():
        if v:
            rein[k] = ledger.cents(v)
    ded = {k: ledger.cents(v) for k, v in (deductions or {}).items() if v}
    r_fiscal = resultat + sum(rein.values()) - sum(ded.values())
    fiscal = {"resultat_comptable": E(resultat), "reintegrations": {k: E(v) for k, v in rein.items()},
              "deductions": {k: E(v) for k, v in ded.items()},
              "370 Résultat fiscal — bénéfice": E(max(r_fiscal, 0)), "372 Résultat fiscal — déficit": E(max(-r_fiscal, 0))}
    # ---- 2033-C immobilisations
    immos = [{"bien": a["label"], "date": a["date"], "valeur_brute": E(a["cost"]), "amortissements_cumules": E(a["amortized"]),
              "valeur_nette": E(a["cost"] - a["amortized"]), "duree": a["years"]}
             for a in con.execute("SELECT * FROM assets WHERE entity_id=? AND date<=?", (eid, e))]
    # ---- 2065 IS
    is_ = tax.impot_societes(r_fiscal / 100, pme, year)
    ent = ledger.entity(con, eid)
    f2065 = {"Dénomination": ent["name"], "SIREN": (ent.get("siret") or "")[:11].replace(" ", ""), "Exercice": f"{s} → {e}",
             "Régime": "Réel simplifié (RSI)", "Résultat fiscal": E(r_fiscal), "IS au taux réduit (15 %)": round(min(max(r_fiscal / 100, 0), 42500) * .15) if pme else 0,
             "IS total": is_["is"], "Acompte trimestriel": is_["acomptes_trimestriels"]}
    fmt = lambda rows: [{"ligne": c, "libelle": l, "montant": E(v)} for c, l, v in rows]
    return {"annee": year, "2033A_actif": fmt(actif), "2033A_passif": fmt(passif), "equilibre": ta == tp,
            "2033B": fmt(compte), "resultat_fiscal": fiscal, "2033C": immos, "2065": f2065,
            "avertissement": "Liasse simplifiée générée depuis la comptabilité. Numéros de lignes à contrôler sur le CERFA de l'année ; "
                             "compléter 2033-D (provisions, déficits), 2033-E (valeur ajoutée/CVAE), 2033-F/G (capital, filiales) si applicable."}
