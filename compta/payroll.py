"""Paie : bulletins de salaire, cotisations, prélèvement à la source, écritures et DSN.

⚠ Taux et plafonds paramétrés par année (PAIE). Ils changent chaque 1er janvier (et parfois en cours
d'année) : à vérifier sur urssaf.fr / agirc-arrco.fr avant tout usage réel. Cas non gérés : temps
partiel thérapeutique, absences et indemnités journalières, heures supplémentaires défiscalisées,
avantages en nature, apprentis, contrats aidés, conventions collectives spécifiques, taxe sur les salaires.
"""
import json, datetime as dt, calendar
from . import ledger, db

PAIE = {
  2026: {
    "pmss": 4005.00, "smic_mensuel": 1823.03, "smic_horaire": 12.02,
    "maladie_seuil_smic": 2.25, "af_seuil_smic": 3.3, "atmp": 0.80,
    "reduction_generale": {"T": 0.3193, "T_50": 0.3233, "note": "Formule 2025 — la RGDU 2026 doit être paramétrée"},
    # Grille de taux neutre du prélèvement à la source (métropole), mensuelle : (plafond net imposable, taux %)
    "pas_neutre": [(1620, 0), (1683, .5), (1791, 1.3), (1911, 2.1), (2042, 2.9), (2151, 3.5), (2294, 4.1), (2714, 5.3),
                   (3107, 7.5), (3539, 9.9), (3983, 11.9), (4648, 13.8), (5574, 15.8), (6974, 17.9), (8711, 20),
                   (12091, 24), (16376, 28), (25706, 33), (55062, 38), (None, 43)],
  },
}
PAIE[2025] = PAIE[2026]

def params(year):
    return PAIE.get(int(year)) or PAIE[max(PAIE)]

# (code DSN indicatif, libellé, assiette, taux salarial %, taux patronal %, organisme, condition)
def _cotisations(p, brut, cadre, effectif):
    smic = p["smic_mensuel"]
    ta = min(brut, p["pmss"])
    t2 = min(max(brut - p["pmss"], 0), 7 * p["pmss"])
    b4 = min(brut, 4 * p["pmss"])
    csg = brut * 0.9825 if brut <= 4 * p["pmss"] * 1 else 4 * p["pmss"] * 0.9825 + (brut - 4 * p["pmss"])
    L = [
        ("100", "Maladie, maternité, invalidité, décès", brut, 0, 7.00 if brut <= p["maladie_seuil_smic"] * smic else 13.00, "urssaf"),
        ("100P", "Assurance vieillesse plafonnée", ta, 6.90, 8.55, "urssaf"),
        ("100D", "Assurance vieillesse déplafonnée", brut, 0.40, 2.11, "urssaf"),
        ("AF", "Allocations familiales", brut, 0, 3.45 if brut <= p["af_seuil_smic"] * smic else 5.25, "urssaf"),
        ("ATMP", "Accidents du travail - maladies professionnelles", brut, 0, p["atmp"], "urssaf"),
        ("CSA", "Contribution solidarité autonomie", brut, 0, 0.30, "urssaf"),
        ("FNAL", "FNAL", ta if effectif < 50 else brut, 0, 0.10 if effectif < 50 else 0.50, "urssaf"),
        ("CHOM", "Assurance chômage", b4, 0, 4.00, "urssaf"),
        ("AGS", "AGS (garantie des salaires)", b4, 0, 0.25, "urssaf"),
        ("DIAL", "Contribution au dialogue social", brut, 0, 0.016, "urssaf"),
        ("FP", "Formation professionnelle", brut, 0, 0.55 if effectif < 11 else 1.00, "urssaf"),
        ("TA", "Taxe d'apprentissage", brut, 0, 0.68, "urssaf"),
        ("RC1", "Retraite complémentaire Agirc-Arrco T1", ta, 3.15, 4.72, "retraite"),
        ("CEG1", "Contribution d'équilibre général T1", ta, 0.86, 1.29, "retraite"),
    ]
    if t2:
        L += [("RC2", "Retraite complémentaire Agirc-Arrco T2", t2, 8.64, 12.95, "retraite"),
              ("CEG2", "Contribution d'équilibre général T2", t2, 1.08, 1.62, "retraite"),
              ("CET", "Contribution d'équilibre technique", brut if brut > p["pmss"] else 0, 0.14, 0.21, "retraite")]
    if cadre:
        L += [("APEC", "APEC", b4, 0.024, 0.036, "retraite"), ("PREV", "Prévoyance cadre (minimum conventionnel)", ta, 0, 1.50, "retraite")]
    L += [("CSGD", "CSG déductible de l'impôt sur le revenu", csg, 6.80, 0, "urssaf"),
          ("CSGN", "CSG/CRDS non déductible", csg, 2.90, 0, "urssaf")]
    return L

def _reduction_generale(p, brut, heures, effectif):
    """Réduction générale des cotisations patronales (formule « Fillon »)."""
    smic_ref = p["smic_horaire"] * heures
    if brut <= 0 or brut >= 1.6 * smic_ref:
        return 0.0
    T = p["reduction_generale"]["T" if effectif < 50 else "T_50"]
    coef = min(T, round(T / 0.6 * (1.6 * smic_ref / brut - 1), 4))
    return round(coef * brut, 2)

def pas_rate(p, net_imposable, taux_perso):
    if taux_perso is not None and taux_perso != "":
        return float(taux_perso), "personnalisé"
    for plafond, taux in p["pas_neutre"]:
        if plafond is None or net_imposable < plafond:
            return taux, "neutre"

def compute(employee, period, effectif=1, extras=None):
    """employee : dict (brut en euros, heures, statut, taux_pas, mutuelle en euros/mois). period : 'AAAA-MM'."""
    y = int(period[:4])
    p = params(y)
    extras = extras or {}
    brut = round(float(employee["brut"]) + float(extras.get("primes") or 0), 2)
    heures = float(employee.get("heures") or 151.67)
    cadre = employee.get("statut") == "cadre"
    lignes, tot_s, tot_p, org = [], 0.0, 0.0, {"urssaf": [0, 0], "retraite": [0, 0], "mutuelle": [0, 0]}
    for code, lib, base, ts, tp, o in _cotisations(p, brut, cadre, effectif):
        ms, mp = round(base * ts / 100, 2), round(base * tp / 100, 2)
        if not ms and not mp:
            continue
        lignes.append({"code": code, "libelle": lib, "base": round(base, 2), "taux_sal": ts, "sal": ms, "taux_pat": tp, "pat": mp, "org": o})
        tot_s += ms; tot_p += mp; org[o][0] += ms; org[o][1] += mp
    mut = float(employee.get("mutuelle") or 0)
    if mut:
        ms, mp = round(mut / 2, 2), round(mut - mut / 2, 2)
        lignes.append({"code": "MUT", "libelle": "Complémentaire santé (50 % employeur)", "base": mut, "taux_sal": None, "sal": ms, "taux_pat": None, "pat": mp, "org": "mutuelle"})
        tot_s += ms; tot_p += mp; org["mutuelle"][0] += ms; org["mutuelle"][1] += mp
    rg = _reduction_generale(p, brut, heures, effectif)
    if rg:
        lignes.append({"code": "RG", "libelle": "Réduction générale des cotisations patronales", "base": brut, "taux_sal": None, "sal": 0, "taux_pat": None, "pat": -rg, "org": "urssaf"})
        tot_p -= rg; org["urssaf"][1] -= rg
    csg_nd = next((l["sal"] for l in lignes if l["code"] == "CSGN"), 0)
    net_social = round(brut - tot_s, 2)
    net_imposable = round(net_social + csg_nd + (mut - mut / 2 if mut else 0), 2)
    taux, type_taux = pas_rate(p, net_imposable, employee.get("taux_pas"))
    pas = round(net_imposable * taux / 100, 2)
    net_payer = round(net_social - pas, 2)
    last = calendar.monthrange(y, int(period[5:7]))[1]
    return {"periode": period, "debut": f"{period}-01", "fin": f"{period}-{last:02d}", "brut": brut, "heures": heures, "lignes": lignes,
            "total_salarial": round(tot_s, 2), "total_patronal": round(tot_p, 2), "net_social": net_social,
            "net_imposable": net_imposable, "taux_pas": taux, "type_taux_pas": type_taux, "pas": pas, "net_a_payer": net_payer,
            "cout_employeur": round(brut + tot_p, 2), "organismes": {k: [round(a, 2), round(b, 2)] for k, (a, b) in org.items()},
            "avertissement": "Taux " + str(y) + " paramétrés dans compta/payroll.py — à vérifier. " + p["reduction_generale"]["note"] + "."}

def run_payroll(con, eid, period, extras=None):
    """Calcule et comptabilise les bulletins du mois pour tous les salariés actifs."""
    effectif = int(db.get_setting(con, eid, "effectif", 1) or 1)
    out = []
    for emp in con.execute("SELECT * FROM employees WHERE entity_id=? AND actif=1", (eid,)).fetchall():
        e = dict(emp)
        if e["date_entree"] and e["date_entree"][:7] > period:
            continue
        if con.execute("SELECT 1 FROM payslips WHERE employee_id=? AND period=?", (e["id"], period)).fetchone():
            continue
        e["brut"] = e["brut"] / 100; e["mutuelle"] = (e["mutuelle"] or 0) / 100
        b = compute(e, period, effectif, (extras or {}).get(str(e["id"])))
        b["salarie"] = {k: e[k] for k in ("nom", "prenom", "nir", "emploi", "statut", "contrat", "date_entree")}
        c = ledger.cents
        o = b["organismes"]
        sal_urssaf, sal_ret = c(o["urssaf"][0]), c(o["retraite"][0]) + c(o["mutuelle"][0])
        pat_urssaf, pat_ret = c(o["urssaf"][1]), c(o["retraite"][1]) + c(o["mutuelle"][1])
        brut_c, pas_c = c(b["brut"]), c(b["pas"])
        net_c = brut_c - sal_urssaf - sal_ret - pas_c  # équilibre au centime près
        lines = [{"account": "641", "debit": brut_c}, {"account": "431", "credit": sal_urssaf}, {"account": "437", "credit": sal_ret},
                 {"account": "4421", "credit": pas_c}, {"account": "421", "credit": net_c},
                 {"account": "645", "debit": pat_urssaf + pat_ret}, {"account": "431", "credit": pat_urssaf}, {"account": "437", "credit": pat_ret}]
        lines = [l for l in lines if (l.get("debit") or l.get("credit") or 0) > 0]
        en = ledger.post_entry(con, eid, b["fin"], "OD", f"Paie {period} — {e['prenom']} {e['nom']}", lines, ref=f"PAIE-{period}-{e['id']}", source="paie")
        b["net_a_payer"] = net_c / 100
        sid = con.execute("INSERT INTO payslips(entity_id,employee_id,period,data,entry_id) VALUES(?,?,?,?,?)",
                          (eid, e["id"], period, json.dumps(b, ensure_ascii=False), en)).lastrowid
        out.append({"id": sid, "salarie": f"{e['prenom']} {e['nom']}", "brut": b["brut"], "net_a_payer": b["net_a_payer"], "cout": b["cout_employeur"]})
    return out

# ---------------- DSN (norme NEODeS) ----------------
def dsn(con, eid, period, test=True):
    """Génère une DSN mensuelle (structure NEODeS : rubriques S10/S20/S21/S90).
    À contrôler avec l'outil DSN-Val avant dépôt sur net-entreprises.fr (ou via le connecteur EDI)."""
    ent = ledger.entity(con, eid)
    siret = (ent.get("siret") or "").replace(" ", "")
    siren, nic = siret[:9] or "000000000", siret[9:14] or "00000"
    mm, yy = period[5:7], period[:4]
    R = []
    add = lambda k, v: R.append(f"{k},'{str(v).replace(chr(39), ' ')}'")
    add("S10.G00.00.001", "ComptaIA"); add("S10.G00.00.002", "The Herakles"); add("S10.G00.00.003", "1.0")
    add("S10.G00.00.005", "02" if test else "01"); add("S10.G00.00.006", "P26V01"); add("S10.G00.00.008", "01")
    add("S10.G00.01.001", siren); add("S10.G00.01.002", nic); add("S10.G00.01.003", ent["name"][:80])
    add("S10.G00.01.004", (ent.get("address") or "")[:50])
    add("S10.G00.02.002", ent["name"][:80]); add("S10.G00.02.004", ent.get("email") or "contact@example.fr")
    add("S20.G00.05.001", "01"); add("S20.G00.05.002", "01"); add("S20.G00.05.003", "11"); add("S20.G00.05.004", "1")
    add("S20.G00.05.005", f"01{mm}{yy}"); add("S20.G00.05.010", "01"); add("S20.G00.05.012", "01")
    add("S21.G00.06.001", siren); add("S21.G00.06.002", nic); add("S21.G00.11.001", nic)
    add("S21.G00.11.008", db.get_setting(con, eid, "effectif", 1))
    tot_urssaf = 0.0
    slips = con.execute("SELECT p.data, e.* FROM payslips p JOIN employees e ON e.id=p.employee_id WHERE p.entity_id=? AND p.period=?", (eid, period)).fetchall()
    for s in slips:
        b = json.loads(s["data"])
        add("S21.G00.30.001", (s["nir"] or "").replace(" ", "")); add("S21.G00.30.002", s["nom"]); add("S21.G00.30.004", s["prenom"])
        if s["naissance"]:
            d = s["naissance"]; add("S21.G00.30.006", f"{d[8:10]}{d[5:7]}{d[:4]}")
        de = s["date_entree"] or b["debut"]
        add("S21.G00.40.001", f"{de[8:10]}{de[5:7]}{de[:4]}"); add("S21.G00.40.002", "04" if s["statut"] == "cadre" else "07")
        add("S21.G00.40.003", "01" if s["statut"] == "cadre" else "02"); add("S21.G00.40.007", "01" if s["contrat"] == "CDI" else "02")
        add("S21.G00.40.009", f"C{s['id']:05d}"); add("S21.G00.40.013", f"{s['heures'] or 151.67:.2f}")
        f = b["fin"]
        add("S21.G00.50.001", f"{f[8:10]}{f[5:7]}{f[:4]}"); add("S21.G00.50.002", f"{b['net_imposable']:.2f}")
        add("S21.G00.50.006", f"{b['taux_pas']:.2f}"); add("S21.G00.50.007", "01" if b["type_taux_pas"] == "personnalisé" else "17")
        add("S21.G00.50.009", f"{b['pas']:.2f}"); add("S21.G00.50.013", f"{b['net_a_payer']:.2f}")
        add("S21.G00.51.001", f"01{mm}{yy}"); add("S21.G00.51.002", f"{f[8:10]}{f[5:7]}{f[:4]}")
        add("S21.G00.51.010", f"C{s['id']:05d}"); add("S21.G00.51.011", "001"); add("S21.G00.51.013", f"{b['brut']:.2f}")
        for code, base in (("02", min(b["brut"], params(yy)["pmss"])), ("03", b["brut"]), ("04", b["brut"] * .9825)):
            add("S21.G00.78.001", code); add("S21.G00.78.002", f"01{mm}{yy}"); add("S21.G00.78.003", f"{f[8:10]}{f[5:7]}{f[:4]}"); add("S21.G00.78.004", f"{base:.2f}")
        for l in b["lignes"]:
            add("S21.G00.81.001", l["code"]); add("S21.G00.81.003", f"{l['base']:.2f}"); add("S21.G00.81.004", f"{l['sal'] + l['pat']:.2f}")
        tot_urssaf += b["organismes"]["urssaf"][0] + b["organismes"]["urssaf"][1]
    add("S21.G00.20.001", "URSSAF"); add("S21.G00.20.005", f"{tot_urssaf:.2f}"); add("S21.G00.20.010", "05")
    add("S90.G00.90.001", len(R) + 2); add("S90.G00.90.002", 1)
    return {"contenu": "\n".join(R) + "\n", "salaries": len(slips), "total_urssaf": round(tot_urssaf, 2),
            "avertissement": "Structure NEODeS simplifiée : contrôler avec DSN-Val (net-entreprises.fr) avant tout dépôt réel. "
                             "Les codes de cotisations individuelles (S21.G00.81) sont indicatifs."}

def pay_salaries(con, eid, period, date):
    """Virement des salaires nets du mois : 421 → 512."""
    tot = 0
    for r in con.execute("SELECT entry_id FROM payslips WHERE entity_id=? AND period=?", (eid, period)):
        tot += con.execute("SELECT COALESCE(SUM(credit),0) FROM lines WHERE entry_id=? AND account='421'", (r[0],)).fetchone()[0]
    already = con.execute("SELECT 1 FROM entries WHERE entity_id=? AND ref=?", (eid, f"VIRSAL-{period}")).fetchone()
    if already:
        raise ledger.LedgerError("Les salaires de ce mois ont déjà été virés")
    if not tot:
        raise ledger.LedgerError("Aucun bulletin pour cette période")
    return ledger.post_entry(con, eid, date, "BQ", f"Virement des salaires {period}", [{"account": "421", "debit": tot}, {"account": "512", "credit": tot}],
                             ref=f"VIRSAL-{period}", source="paie")
