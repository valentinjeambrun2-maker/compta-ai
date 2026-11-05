"""Calculs fiscaux français : IR (déclaration 2042), IS, TVA (CA3), micro-entreprise.

⚠ Les barèmes ci-dessous sont paramétrés par ANNÉE DE REVENUS et doivent être
vérifiés chaque année (loi de finances) avant tout usage réel. Les numéros de
cases sont indicatifs : contrôlez-les sur le formulaire officiel de l'année.
"""
from . import ledger

PARAMS = {
  2025: {  # revenus 2025, déclarés au printemps 2026
    "brackets": [(11600, 0.0), (29579, .11), (84577, .30), (181917, .41), (None, .45)],
    "plafond_demi_part": 1807,
    "decote": {"seul": (1982, 897), "couple": (3277, 1483), "taux": .4525},
    "frais_pro": {"taux": .10, "min": 509, "max": 14555},
    "pensions": {"taux": .10, "min": 454, "max": 4439},
    "micro": {"bic_vente": .71, "bic_service": .50, "bnc": .34, "min": 305},
    "micro_foncier": {"abattement": .30, "plafond": 15000},
    "ps": .172, "pfu_ir": .128,
    "dons": {"general": .66, "aide": .75, "plafond_aide": 1000, "limite_revenu": .20},
    "emploi_domicile": {"taux": .5, "plafond": 12000},
    "garde": {"taux": .5, "plafond": 3500},
    "is": {"reduit": .15, "seuil_reduit": 42500, "normal": .25},
    "urssaf_micro": {"bic_vente": .123, "bic_service": .212, "bnc": .246},
  },
}
PARAMS[2026] = PARAMS[2025]  # en attente de la loi de finances : à mettre à jour

def params(year):
    return PARAMS.get(int(year)) or PARAMS[max(PARAMS)]

def _bareme(revenu_par_part, p):
    impot, bas, tmi = 0.0, 0, 0.0
    for haut, taux in p["brackets"]:
        haut_eff = revenu_par_part if haut is None else min(haut, revenu_par_part)
        if haut_eff > bas:
            impot += (haut_eff - bas) * taux
            tmi = taux
        if haut is None or revenu_par_part <= haut:
            break
        bas = haut
    return impot, tmi

def parts(situation, enfants):
    base = 2 if situation in ("marie", "pacse") else 1
    e = int(enfants or 0)
    return base, base + 0.5 * min(e, 2) + max(0, e - 2)

def impot_revenu(d, year=2025):
    """d : dict des revenus et charges annuels en euros. Renvoie le calcul détaillé + cases 2042."""
    p = params(year)
    f = lambda k: float(d.get(k) or 0)
    sal, fr = f("salaires"), f("frais_reels")
    abatt_sal = fr if fr else (min(max(sal * p["frais_pro"]["taux"], p["frais_pro"]["min"]), p["frais_pro"]["max"]) if sal else 0)
    abatt_sal = min(abatt_sal, sal)
    pen = f("pensions")
    abatt_pen = min(min(max(pen * p["pensions"]["taux"], p["pensions"]["min"]), p["pensions"]["max"]), pen) if pen else 0
    m = p["micro"]
    micro = 0.0
    for k, taux in (("micro_bic_vente", m["bic_vente"]), ("micro_bic_service", m["bic_service"]), ("micro_bnc", m["bnc"])):
        if f(k):
            micro += max(f(k) * (1 - taux), 0) if f(k) * taux >= m["min"] else max(f(k) - m["min"], 0)
    loyers = f("loyers_micro_foncier")
    if loyers > p["micro_foncier"]["plafond"]:
        notes_foncier = "Loyers > 15 000 € : régime réel obligatoire (déclaration 2044) — calcul indicatif."
    else:
        notes_foncier = None
    foncier = loyers * (1 - p["micro_foncier"]["abattement"])
    rbg = (sal - abatt_sal) + (pen - abatt_pen) + micro + foncier
    deductions = f("pension_alimentaire") + f("per_versements") + f("autres_deductions")
    rni = max(0.0, rbg - deductions)
    base_parts, nb_parts = parts(d.get("situation", "celibataire"), d.get("enfants"))
    if d.get("parts"):
        nb_parts = float(d["parts"])
    i_qf = _bareme(rni / nb_parts, p)[0] * nb_parts
    i_base, _ = _bareme(rni / base_parts, p)
    i_base *= base_parts
    tmi = _bareme(rni / nb_parts, p)[1]
    plafond = p["plafond_demi_part"] * (nb_parts - base_parts) / 0.5
    plafonnement = max(0.0, (i_base - i_qf) - plafond)
    brut = i_qf + plafonnement
    seuil, base_dec = p["decote"]["couple" if base_parts == 2 else "seul"]
    decote = min(brut, max(0.0, base_dec - p["decote"]["taux"] * brut)) if brut <= seuil else 0.0
    apres_decote = brut - decote
    # Réductions (non remboursables)
    dons_aide = min(f("dons_aide"), p["dons"]["plafond_aide"])
    dons_gen = f("dons") + max(0, f("dons_aide") - p["dons"]["plafond_aide"])
    dons_gen = min(dons_gen, rni * p["dons"]["limite_revenu"])
    red_dons = dons_aide * p["dons"]["aide"] + dons_gen * p["dons"]["general"]
    reductions = min(apres_decote, red_dons)
    # Crédits (remboursables)
    enfants_moins_6 = int(d.get("enfants_moins_6") or (1 if f("garde_enfants") else 0))
    credit_garde = min(f("garde_enfants"), p["garde"]["plafond"] * max(enfants_moins_6, 1)) * p["garde"]["taux"]
    credit_dom = min(f("emploi_domicile"), p["emploi_domicile"]["plafond"]) * p["emploi_domicile"]["taux"]
    capitaux = f("dividendes") + f("interets")
    pfu = capitaux * p["pfu_ir"]
    ps = (capitaux + foncier) * p["ps"]
    net_ir = apres_decote - reductions - credit_garde - credit_dom + pfu
    total = net_ir + ps
    r = lambda x: round(x)
    cases = {k: r(v) for k, v in {
        "1AJ Salaires": sal, "1AK Frais réels": fr, "1AS Pensions, retraites": pen, "4BE Micro-foncier (loyers bruts)": loyers,
        "2DC Dividendes": f("dividendes"), "2TR Intérêts": f("interets"), "5KO Micro-BIC ventes (CA)": f("micro_bic_vente"),
        "5KP Micro-BIC services (CA)": f("micro_bic_service"), "5HQ Micro-BNC (recettes)": f("micro_bnc"),
        "6DD Pension alimentaire versée": f("pension_alimentaire"), "6NS Versements PER": f("per_versements"),
        "7UF Dons intérêt général": f("dons"), "7UD Dons aide aux personnes": f("dons_aide"),
        "7DB Emploi à domicile": f("emploi_domicile"), "7GA Garde d'enfants hors domicile": f("garde_enfants")}.items() if v}
    revenus_tot = sal + pen + f("micro_bic_vente") + f("micro_bic_service") + f("micro_bnc") + loyers + capitaux
    notes = [n for n in [notes_foncier,
        "Option pour le barème progressif sur les revenus de capitaux non simulée (PFU 12,8 % + PS 17,2 % appliqués)." if capitaux else None,
        "Plafond PER non contrôlé : vérifiez le montant déductible sur votre avis d'imposition." if f("per_versements") else None,
        "Plafonnement du quotient familial appliqué." if plafonnement else None] if n]
    return {"annee_revenus": int(year), "parts": nb_parts, "revenu_brut_global": r(rbg), "revenu_net_imposable": r(rni),
            "impot_bareme": r(i_qf), "plafonnement_qf": r(plafonnement), "impot_brut": r(brut), "decote": r(decote),
            "reductions": r(reductions), "credits": r(credit_garde + credit_dom), "pfu_ir": r(pfu), "impot_revenu_net": r(net_ir),
            "prelevements_sociaux": r(ps), "total_a_payer": r(total), "tmi": f"{tmi*100:.0f} %",
            "taux_moyen": f"{(total / revenus_tot * 100) if revenus_tot else 0:.1f} %", "cases_2042": cases, "notes": notes}

def impot_societes(resultat_eur, pme=True, year=2025):
    p = params(year)["is"]
    if resultat_eur <= 0:
        return {"base": round(resultat_eur), "is": 0, "detail": "Déficit : aucun IS, report en avant possible."}
    red = min(resultat_eur, p["seuil_reduit"]) if pme else 0
    is_ = red * p["reduit"] + (resultat_eur - red) * p["normal"]
    return {"base": round(resultat_eur), "is": round(is_), "taux_reduit_sur": round(red),
            "acomptes_trimestriels": round(is_ / 4) if is_ > 3000 else 0,
            "detail": "15 % jusqu'à 42 500 € (PME : CA < 10 M€, capital libéré détenu ≥ 75 % par des personnes physiques), 25 % au-delà."}

def micro_entreprise(ca_eur, activite="bnc", versement_liberatoire=False, year=2025):
    p = params(year)
    cot = ca_eur * p["urssaf_micro"][activite]
    vl = {"bic_vente": .01, "bic_service": .017, "bnc": .022}[activite] * ca_eur if versement_liberatoire else 0
    return {"ca": round(ca_eur), "cotisations_urssaf": round(cot), "versement_liberatoire": round(vl),
            "revenu_imposable_micro": round(ca_eur * (1 - p["micro"][activite])), "net_avant_ir": round(ca_eur - cot - vl),
            "note": "Taux URSSAF à vérifier selon l'année et l'activité (hors CFP, ACRE non appliquée)."}

def ca3(con, eid, start, end):
    """Déclaration de TVA CA3 (régime réel normal) à partir des écritures."""
    def by_rate(acc, sign):
        out = {}
        for r in con.execute("""SELECT l.rate, SUM(l.base) b, SUM(l.credit-l.debit) t FROM lines l JOIN entries e ON e.id=l.entry_id
            WHERE e.entity_id=? AND l.account=? AND e.date BETWEEN ? AND ? GROUP BY l.rate""", (eid, acc, start, end)):
            out[r["rate"] or 0] = {"base": r["b"] or 0, "tva": sign * (r["t"] or 0)}
        return out
    col, ded = by_rate("44571", 1), by_rate("44566", -1)
    g = lambda d, rate, k: d.get(rate, {}).get(k, 0)
    brute = sum(v["tva"] for v in col.values())
    deductible = sum(v["tva"] for v in ded.values())
    net = brute - deductible
    e = ledger.euros
    ventes_ht = sum(v["base"] for v in col.values())
    lignes = {
        "A01 Ventes, prestations de services (HT)": e(ventes_ht),
        "08 Taux normal 20 % — base HT": e(g(col, 20.0, "base")), "08 Taux normal 20 % — TVA": e(g(col, 20.0, "tva")),
        "9B Taux 10 % — base HT": e(g(col, 10.0, "base")), "9B Taux 10 % — TVA": e(g(col, 10.0, "tva")),
        "09 Taux 5,5 % — base HT": e(g(col, 5.5, "base")), "09 Taux 5,5 % — TVA": e(g(col, 5.5, "tva")),
        "16 Total TVA brute due": e(brute), "19 TVA déductible sur autres biens et services": e(deductible),
        "23 Total TVA déductible": e(deductible), "25 Crédit de TVA": e(max(0, -net)),
        "28 TVA nette due": e(max(0, net)), "32 Total à payer": e(max(0, net))}
    return {"periode": f"{start} → {end}", "lignes": lignes, "a_payer": e(max(0, net)), "credit": e(max(0, -net)),
            "collectee": e(brute), "deductible": e(deductible), "net_cents": net}

def post_tva_settlement(con, eid, start, end):
    """Écriture de liquidation de TVA : solde 44571/44566 vers 44551 (ou 44567 si crédit)."""
    d = ca3(con, eid, start, end)
    col, ded = ledger.cents(d["collectee"]), ledger.cents(d["deductible"])
    if not col and not ded:
        raise ledger.LedgerError("Aucune TVA sur la période")
    net = col - ded
    lines = [{"account": "44571", "debit": col}, {"account": "44566", "credit": ded}]
    lines.append({"account": "44551", "credit": net} if net > 0 else {"account": "44567", "debit": -net})
    return ledger.post_entry(con, eid, end, "OD", f"Liquidation TVA {start} → {end}", [l for l in lines if l.get("debit") or l.get("credit")], source="tva")
