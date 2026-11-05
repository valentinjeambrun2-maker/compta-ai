"""Revenus fonciers au régime réel : déclaration 2044 et report sur la 2042 (4BA, 4BB, 4BC, 4BD).

Règles (CGI art. 28 à 31 et 156-I-3°) : charges déductibles par bien ; le déficit provenant des
intérêts d'emprunt ne s'impute que sur les revenus fonciers des 10 années suivantes ; le reste
s'impute sur le revenu global dans la limite de 10 700 € par an (21 400 € pour certains travaux de
rénovation énergétique, non simulé), l'excédent étant reportable 10 ans sur les revenus fonciers.
"""
FORFAIT_GESTION = 20      # € par local (ligne 222)
PLAFOND_DEFICIT = 10700   # € imputables sur le revenu global

CHARGES = [("frais_administration", "221 Frais d'administration et de gestion"), ("assurance", "223 Primes d'assurance"),
           ("travaux", "224 Travaux de réparation, d'entretien et d'amélioration"), ("charges_non_recuperees", "225 Charges récupérables non récupérées au départ du locataire"),
           ("indemnites", "226 Indemnités d'éviction, frais de relogement"), ("taxe_fonciere", "227 Taxe foncière (hors TEOM)"),
           ("provisions_copro", "229 Provisions pour charges de copropriété"), ("regularisation_copro", "230 Régularisation des provisions (à déduire)")]

def compute(biens, deficits_anterieurs=0):
    """biens : [{nom, loyers, frais_administration, assurance, travaux, ..., interets, locaux}] (euros/an)."""
    f = lambda d, k: float(d.get(k) or 0)
    detail, rev, ch, it = [], 0.0, 0.0, 0.0
    for b in biens:
        r = f(b, "loyers") + f(b, "recettes_brutes_diverses")
        c = sum(f(b, k) for k, _ in CHARGES if k != "regularisation_copro") - f(b, "regularisation_copro")
        c += FORFAIT_GESTION * int(b.get("locaux") or 1)
        i = f(b, "interets")
        detail.append({"bien": b.get("nom") or "Bien", "215 Revenus bruts": round(r), "240 Frais et charges": round(c),
                       "250 Intérêts d'emprunt": round(i), "263 Résultat": round(r - c - i)})
        rev += r; ch += c; it += i
    resultat = rev - ch - it
    d_int = max(0.0, it - rev)                 # déficit dû aux intérêts : foncier seulement
    d_autres = max(0.0, ch - max(0.0, rev - it))
    imputable_rg = min(d_autres, PLAFOND_DEFICIT)
    reportable = d_int + (d_autres - imputable_rg)
    ant = float(deficits_anterieurs or 0)
    if resultat > 0:
        imposable = max(0.0, resultat - ant)
        ant_restant = max(0.0, ant - resultat)
    else:
        imposable, ant_restant = 0.0, ant
    cases = {"4BA Résultat foncier (bénéfice)": round(max(resultat, 0)), "4BB Déficit imputable sur les revenus fonciers": round(reportable),
             "4BC Déficit imputable sur le revenu global": round(imputable_rg), "4BD Déficits antérieurs non encore imputés": round(ant)}
    notes = []
    if imputable_rg:
        notes.append("Le déficit imputé sur le revenu global n'est définitif que si le bien reste loué jusqu'au 31/12 de la 3e année suivante.")
    if any(f(b, "loyers") > 0 for b in biens) and rev <= 15000:
        notes.append("Loyers ≤ 15 000 € : le micro-foncier (abattement 30 %) est possible ; comparez avec le réel.")
    return {"biens": detail, "revenus_bruts": round(rev), "charges": round(ch), "interets": round(it), "resultat": round(resultat),
            "revenu_imposable": round(imposable), "deficit_revenu_global": round(imputable_rg), "deficit_reportable": round(reportable),
            "cases_2042": {k: v for k, v in cases.items() if v}, "notes": notes}
