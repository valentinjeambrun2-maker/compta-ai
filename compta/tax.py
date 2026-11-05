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

CASES = {  # clé interne -> (formulaire, case, libellé)
    "salaires": ("2042", "1AJ", "Salaires — déclarant 1"), "salaires_d2": ("2042", "1BJ", "Salaires — déclarant 2"),
    "frais_reels": ("2042", "1AK", "Frais réels — déclarant 1"), "frais_reels_d2": ("2042", "1BK", "Frais réels — déclarant 2"),
    "chomage": ("2042", "1AP", "Allocations chômage — déclarant 1"), "chomage_d2": ("2042", "1BP", "Allocations chômage — déclarant 2"),
    "pensions": ("2042", "1AS", "Pensions, retraites — déclarant 1"), "pensions_d2": ("2042", "1BS", "Pensions, retraites — déclarant 2"),
    "dividendes": ("2042", "2DC", "Revenus d'actions et parts (dividendes)"), "interets": ("2042", "2TR", "Produits de placement à revenu fixe (intérêts)"),
    "loyers_micro_foncier": ("2042", "4BE", "Micro-foncier : recettes brutes"),
    "pension_alimentaire": ("2042", "6GU", "Pensions alimentaires versées"), "per_versements": ("2042", "6NS", "Versements sur un PER — déclarant 1"),
    "dons": ("2042-RICI", "7UF", "Dons aux organismes d'intérêt général"), "dons_aide": ("2042-RICI", "7UD", "Dons aux organismes d'aide aux personnes en difficulté"),
    "emploi_domicile": ("2042-RICI", "7DB", "Sommes versées pour l'emploi d'un salarié à domicile"),
    "garde_enfants": ("2042-RICI", "7GA", "Frais de garde des enfants de moins de 6 ans"), "ehpad": ("2042-RICI", "7CD", "Dépenses d'accueil en établissement pour personnes dépendantes"),
    "micro_bic_vente": ("2042-C-PRO", "5KO", "Micro-BIC : ventes de marchandises (CA)"), "micro_bic_service": ("2042-C-PRO", "5KP", "Micro-BIC : prestations de services (CA)"),
    "micro_bnc": ("2042-C-PRO", "5HQ", "Micro-BNC : recettes"),
    "micro_bic_vente_vl": ("2042-C-PRO", "5TA", "Auto-entrepreneur avec versement libératoire : ventes"),
    "micro_bic_service_vl": ("2042-C-PRO", "5TB", "Auto-entrepreneur avec versement libératoire : prestations BIC"),
    "micro_bnc_vl": ("2042-C-PRO", "5TE", "Auto-entrepreneur avec versement libératoire : BNC"),
}
SCOLARITE = {"college": (61, "7EA"), "lycee": (153, "7EC"), "superieur": (183, "7EF")}

def impot_revenu(d, year=2025):
    """Calcul détaillé de l'impôt sur le revenu d'un foyer. d : revenus et charges annuels (euros).
    Clés reconnues : voir CASES + situation, enfants, parts, frais_reels*, option_bareme, foncier_reel, deficit_foncier_rg,
    cases_foncier, enfants_moins_6, scolarite {college, lycee, superieur}, micro_vl, pas_verse, autres_deductions."""
    p = params(year)
    f = lambda k: float(d.get(k) or 0)
    fp = p["frais_pro"]
    def net_salaires(sal, chom, fr):
        brut = sal + chom
        if not brut:
            return 0.0, 0.0
        ab = fr if fr else min(max(brut * fp["taux"], fp["min"]), fp["max"])
        ab = min(ab, brut)
        return brut - ab, ab
    n1, ab1 = net_salaires(f("salaires"), f("chomage"), f("frais_reels"))
    n2, ab2 = net_salaires(f("salaires_d2"), f("chomage_d2"), f("frais_reels_d2"))
    pen = f("pensions") + f("pensions_d2")
    pp = p["pensions"]
    nb_pens = (1 if f("pensions") else 0) + (1 if f("pensions_d2") else 0)
    abatt_pen = min(max(pen * pp["taux"], pp["min"] * nb_pens), pp["max"], pen) if pen else 0
    m = p["micro"]
    micro, micro_vl_ca = 0.0, 0.0
    vl = bool(d.get("micro_vl"))
    for k, taux in (("micro_bic_vente", m["bic_vente"]), ("micro_bic_service", m["bic_service"]), ("micro_bnc", m["bnc"])):
        ca = f(k)
        if ca:
            net = max(ca * (1 - taux), 0) if ca * taux >= m["min"] else max(ca - m["min"], 0)
            if vl:
                micro_vl_ca += net
            else:
                micro += net
    loyers = f("loyers_micro_foncier")
    notes = []
    if loyers > p["micro_foncier"]["plafond"]:
        notes.append("Loyers > 15 000 € : régime réel obligatoire (déclaration 2044).")
    foncier = loyers * (1 - p["micro_foncier"]["abattement"])
    reel = f("foncier_reel")
    if loyers and (reel or f("deficit_foncier_rg")):
        notes.append("Micro-foncier et régime réel ne peuvent pas être cumulés : choisissez l'un des deux.")
    foncier += reel
    capitaux = f("dividendes") + f("interets")
    option_bareme = bool(d.get("option_bareme"))
    cap_bareme = (f("dividendes") * 0.6 + f("interets")) if option_bareme else 0.0
    rbg = max(0.0, n1 + n2 + (pen - abatt_pen) + micro + foncier + cap_bareme - f("deficit_foncier_rg"))
    deductions = f("pension_alimentaire") + f("per_versements") + f("autres_deductions")
    rni = max(0.0, rbg - deductions)
    base_parts, nb_parts = parts(d.get("situation", "celibataire"), d.get("enfants"))
    if d.get("parts"):
        nb_parts = float(d["parts"])
    i_qf, tmi = _bareme(rni / nb_parts, p)
    i_qf *= nb_parts
    i_base = _bareme(rni / base_parts, p)[0] * base_parts
    plafond = p["plafond_demi_part"] * (nb_parts - base_parts) / 0.5
    plafonnement = max(0.0, (i_base - i_qf) - plafond)
    brut = i_qf + plafonnement
    seuil, base_dec = p["decote"]["couple" if base_parts == 2 else "seul"]
    decote = min(brut, max(0.0, base_dec - p["decote"]["taux"] * brut)) if brut <= seuil else 0.0
    apres_decote = brut - decote
    # Réductions d'impôt (non remboursables)
    dons_aide = min(f("dons_aide"), p["dons"]["plafond_aide"])
    dons_gen = min(f("dons") + max(0, f("dons_aide") - p["dons"]["plafond_aide"]), rni * p["dons"]["limite_revenu"])
    red = {"Dons": dons_aide * p["dons"]["aide"] + dons_gen * p["dons"]["general"],
           "Hébergement en établissement (EHPAD)": min(f("ehpad"), 10000) * 0.25}
    sco = d.get("scolarite") or {}
    red["Frais de scolarité"] = sum(SCOLARITE[k][0] * int(sco.get(k) or 0) for k in SCOLARITE)
    tot_red = sum(red.values())
    reductions = min(apres_decote, tot_red)
    # Crédits d'impôt (remboursables)
    e6 = int(d.get("enfants_moins_6") or (1 if f("garde_enfants") else 0))
    credit_garde = min(f("garde_enfants"), p["garde"]["plafond"] * max(e6, 1)) * p["garde"]["taux"]
    plaf_dom = min(p["emploi_domicile"]["plafond"] + 1500 * int(d.get("enfants") or 0), 15000)
    credit_dom = min(f("emploi_domicile"), plaf_dom) * p["emploi_domicile"]["taux"]
    pfu = 0.0 if option_bareme else capitaux * p["pfu_ir"]
    ps = (capitaux + foncier) * p["ps"]
    net_ir = apres_decote - reductions - credit_garde - credit_dom + pfu
    total = net_ir + ps
    pas = f("pas_verse")
    r = lambda x: round(x)
    formulaires = {}
    def add(key, val):
        if val:
            form, case, lab = CASES[key]
            formulaires.setdefault(form, []).append({"case": case, "libelle": lab, "montant": r(val)})
    for k in ("salaires", "salaires_d2", "frais_reels", "frais_reels_d2", "chomage", "chomage_d2", "pensions", "pensions_d2",
              "dividendes", "interets", "loyers_micro_foncier", "pension_alimentaire", "per_versements", "dons", "dons_aide",
              "emploi_domicile", "garde_enfants", "ehpad"):
        add(k, f(k))
    for k in ("micro_bic_vente", "micro_bic_service", "micro_bnc"):
        add(k + ("_vl" if vl else ""), f(k))
    if option_bareme:
        formulaires.setdefault("2042", []).append({"case": "2OP", "libelle": "Option pour l'imposition au barème des revenus de capitaux", "montant": "☑"})
    for k, (mt, case) in SCOLARITE.items():
        if int(sco.get(k) or 0):
            n = int(sco[k])
            formulaires.setdefault("2042-RICI", []).append({"case": case, "libelle": f"Enfants scolarisés ({ {'college': 'collège', 'lycee': 'lycée', 'superieur': 'enseignement supérieur'}[k]})",
                                                            "montant": f"{n} enfant{'s' if n > 1 else ''}"})
    for lab, v in (d.get("cases_foncier") or {}).items():
        if v:
            form = "2042" if lab[:3] in ("4BA", "4BB", "4BC", "4BD") else "2044"
            formulaires.setdefault(form, []).append({"case": lab[:3], "libelle": lab[4:], "montant": r(v)})
    cases = {f"{x['case']} {x['libelle']}": x["montant"] for lst in formulaires.values() for x in lst}
    revenus_tot = f("salaires") + f("salaires_d2") + f("chomage") + f("chomage_d2") + pen + f("micro_bic_vente") + f("micro_bic_service") + f("micro_bnc") + loyers + reel + capitaux
    if capitaux and not option_bareme:
        notes.append("Revenus de capitaux au prélèvement forfaitaire (PFU 12,8 % + PS 17,2 %) ; l'option pour le barème (case 2OP) est comparée par l'agent.")
    if f("per_versements"):
        notes.append("Vérifiez que le versement PER respecte le plafond figurant sur votre avis d'impôt.")
    if plafonnement:
        notes.append("Plafonnement du quotient familial appliqué.")
    if vl:
        notes.append("Versement libératoire : chiffre d'affaires non réimposé, mais pris en compte pour le taux effectif et le revenu fiscal de référence.")
    rfr = rni + (0 if option_bareme else capitaux) + micro_vl_ca
    return {"annee_revenus": int(year), "parts": nb_parts, "revenu_brut_global": r(rbg), "revenu_net_imposable": r(rni),
            "revenu_fiscal_reference": r(rfr), "abattements_frais": r(ab1 + ab2), "impot_bareme": r(i_qf), "plafonnement_qf": r(plafonnement),
            "impot_brut": r(brut), "decote": r(decote), "reductions": r(reductions), "detail_reductions": {k: r(v) for k, v in red.items() if v},
            "credits": r(credit_garde + credit_dom), "detail_credits": {k: r(v) for k, v in (("Garde d'enfants", credit_garde), ("Emploi à domicile", credit_dom)) if v},
            "pfu_ir": r(pfu), "impot_revenu_net": r(net_ir), "prelevements_sociaux": r(ps), "total_a_payer": r(total),
            "deja_preleve": r(pas), "solde": r(total - pas), "tmi": f"{tmi*100:.0f} %", "tmi_num": tmi,
            "taux_moyen": f"{(total / revenus_tot * 100) if revenus_tot else 0:.1f} %", "cases_2042": cases, "formulaires": formulaires, "notes": notes}

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
        for r in con.execute(f"""SELECT l.rate, SUM(l.base) b, SUM(l.credit-l.debit) t FROM lines l JOIN entries e ON e.id=l.entry_id
            WHERE e.entity_id=? AND l.account=? AND e.date BETWEEN ? AND ? AND {ledger.SANS_LIQUIDATION_TVA} GROUP BY l.rate""", (eid, acc, start, end)):
            out[r["rate"] or 0] = {"base": r["b"] or 0, "tva": sign * (r["t"] or 0)}
        return out
    col, ded = by_rate("44571", 1), by_rate("44566", -1)
    for k, v in by_rate("4452", 1).items():           # TVA autoliquidée (intracom, import, BTP)
        col.setdefault(k, {"base": 0, "tva": 0}); col[k]["base"] += v["base"]; col[k]["tva"] += v["tva"]
    ded_auto = by_rate("445662", -1)
    ded_immo = by_rate("44562", -1)
    g = lambda d, rate, k: d.get(rate, {}).get(k, 0)
    brute = sum(v["tva"] for v in col.values())
    deductible = sum(v["tva"] for v in ded.values()) + sum(v["tva"] for v in ded_auto.values()) + sum(v["tva"] for v in ded_immo.values())
    from . import vat
    intl = vat.international_lines(con, eid, start, end)
    net = brute - deductible
    e = ledger.euros
    ventes_ht = sum(v["base"] for v in col.values()) - intl["acquisitions_ue_base"]
    t21 = col.get(2.1)   # taux particulier (presse, médicaments remboursables) : sans cette ligne, le détail ne totalise pas la TVA brute
    autres = brute - sum(col.get(r, {}).get("tva", 0) for r in (20.0, 10.0, 5.5, 2.1))
    lignes = {
        "A01 Ventes, prestations de services (HT)": e(ventes_ht),
        "08 Taux normal 20 % — base HT": e(g(col, 20.0, "base")), "08 Taux normal 20 % — TVA": e(g(col, 20.0, "tva")),
        "9B Taux 10 % — base HT": e(g(col, 10.0, "base")), "9B Taux 10 % — TVA": e(g(col, 10.0, "tva")),
        "09 Taux 5,5 % — base HT": e(g(col, 5.5, "base")), "09 Taux 5,5 % — TVA": e(g(col, 5.5, "tva")),
        **({"Taux 2,1 % — base HT": e(t21["base"]), "Taux 2,1 % — TVA": e(t21["tva"])} if t21 else {}),
        **({"Autres taux — TVA": e(autres)} if autres else {}),
        "04 Exportations hors UE (base)": e(intl["exportations"]), "06 Livraisons intracommunautaires (base)": e(intl["livraisons_ue"]),
        "E3 Prestations de services intracommunautaires (base)": e(intl["prestations_ue"]),
        "B2 Acquisitions intracommunautaires / autoliquidation (base)": e(intl["acquisitions_ue_base"]),
        "17 dont TVA due sur acquisitions intracommunautaires / autoliquidée": e(intl["tva_autoliquidee"]),
        "16 Total TVA brute due": e(brute), "19 TVA déductible sur immobilisations": e(sum(v["tva"] for v in ded_immo.values())),
        "20 TVA déductible sur autres biens et services": e(deductible - sum(v["tva"] for v in ded_immo.values())),
        "23 Total TVA déductible": e(deductible), "25 Crédit de TVA": e(max(0, -net)),
        "28 TVA nette due": e(max(0, net)), "32 Total à payer": e(max(0, net))}
    return {"periode": f"{start} → {end}", "lignes": lignes, "a_payer": e(max(0, net)), "credit": e(max(0, -net)),
            "collectee": e(brute), "deductible": e(deductible), "net_cents": net}

def post_tva_settlement(con, eid, start, end):
    """Écriture de liquidation de TVA : solde la TVA collectée (44571, 4452) et déductible (44566, 445662, 44562)
    vers 44551 (TVA à décaisser) ou 44567 (crédit de TVA). La CA3 de la période ignore cette écriture. Une seule fois par période."""
    label = f"Liquidation TVA {start} → {end}"
    if con.execute("SELECT 1 FROM entries WHERE entity_id=? AND source='tva' AND label=?", (eid, label)).fetchone():
        raise ledger.LedgerError("La liquidation de cette période est déjà comptabilisée")
    def solde(acc):   # crédit - débit sur la période, hors liquidations
        return con.execute(f"""SELECT COALESCE(SUM(l.credit - l.debit), 0) FROM lines l JOIN entries e ON e.id = l.entry_id
            WHERE e.entity_id=? AND l.account=? AND e.date BETWEEN ? AND ? AND {ledger.SANS_LIQUIDATION_TVA}""", (eid, acc, start, end)).fetchone()[0]
    lines, collectee, deductible = [], 0, 0
    for acc in ("44571", "4452"):                 # comptes de TVA collectée : créditeurs, on les débite
        b = solde(acc); collectee += b
        if b:
            lines.append({"account": acc, "debit": b} if b > 0 else {"account": acc, "credit": -b})
    for acc in ("44566", "445662", "44562"):      # comptes de TVA déductible : débiteurs, on les crédite
        d = -solde(acc); deductible += d
        if d:
            lines.append({"account": acc, "credit": d} if d > 0 else {"account": acc, "debit": -d})
    if not lines:
        raise ledger.LedgerError("Aucune TVA sur la période")
    net = collectee - deductible
    if net:
        lines.append({"account": "44551", "credit": net} if net > 0 else {"account": "44567", "debit": -net})
    return ledger.post_entry(con, eid, end, "OD", label, lines, source="tva")
