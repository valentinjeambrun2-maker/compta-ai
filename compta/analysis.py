"""Analyse financière : soldes intermédiaires de gestion (SIG), capacité d'autofinancement (CAF), ratios,
besoin en fonds de roulement, seuil de rentabilité, trésorerie prévisionnelle et suivi budgétaire."""
import datetime as dt, re, statistics
from collections import defaultdict
from . import ledger

E = ledger.euros

def _flows(con, eid, start, end):
    """Soldes de gestion par compte (charges positives, produits positifs), hors écritures de clôture."""
    return {b["account"]: b["solde"] for b in ledger.balances(con, eid, start, end, exclude_closing=True) if b["account"][0] in "67"}

def _s(f, prefixes, sign=1, exclude=()):
    return sign * sum(v for k, v in f.items() if any(k.startswith(p) for p in prefixes) and not any(k.startswith(x) for x in exclude))

def sig(con, eid, year):
    s, e = f"{year}-01-01", f"{year}-12-31"
    f = _flows(con, eid, s, e)
    P = lambda *p, exclude=(): -_s(f, p, exclude=exclude)   # produits (solde créditeur)
    C = lambda *p, exclude=(): _s(f, p, exclude=exclude)    # charges (solde débiteur)
    ventes_m = P("707", "709")
    cout_m = C("607", "6037", "609")
    marge_commerciale = ventes_m - cout_m
    production_vendue = P("701", "702", "703", "704", "705", "706", "708")
    production = production_vendue + P("713") + P("72")
    conso = C("601", "602", "6031", "6032", "604", "605", "606", "61", "62")
    va = marge_commerciale + production - conso
    subv = P("74"); impots = C("63"); personnel = C("64")
    ebe = va + subv - impots - personnel
    autres_p = P("75", "781", "791"); autres_c = C("65", "681")
    re_ = ebe + autres_p - autres_c
    rf = P("76", "786") - C("66", "686")
    rcai = re_ + rf
    rex = P("77", "787") - C("67", "687")
    part, is_ = C("691"), C("695", "696", "698", "699")
    net = rcai + rex - part - is_
    caf = net + C("68") - P("78") - P("775") + C("675") - P("777")
    ca = ventes_m + production_vendue
    rows = [("Ventes de marchandises", ventes_m), ("− Coût d'achat des marchandises vendues", -cout_m), ("= Marge commerciale", marge_commerciale),
            ("Production de l'exercice", production), ("− Consommations en provenance des tiers", -conso), ("= Valeur ajoutée", va),
            ("+ Subventions d'exploitation", subv), ("− Impôts et taxes", -impots), ("− Charges de personnel", -personnel),
            ("= Excédent brut d'exploitation (EBE)", ebe), ("+ Reprises, transferts et autres produits", autres_p),
            ("− Dotations et autres charges", -autres_c), ("= Résultat d'exploitation", re_), ("± Résultat financier", rf),
            ("= Résultat courant avant impôt", rcai), ("± Résultat exceptionnel", rex), ("− Participation et impôt sur les bénéfices", -(part + is_)),
            ("= Résultat net", net), ("Capacité d'autofinancement (CAF)", caf)]
    return {"annee": year, "chiffre_affaires": E(ca), "lignes": [{"libelle": l, "montant": E(v), "total": l.startswith("=") or l.startswith("Capacité"),
            "pct_ca": round(v / ca * 100, 1) if ca else None} for l, v in rows],
            "_raw": {"ca": ca, "va": va, "ebe": ebe, "re": re_, "net": net, "caf": caf, "personnel": personnel, "cout_m": cout_m, "conso": conso}}

def ratios(con, eid, year):
    e = f"{year}-12-31"
    g = sig(con, eid, year)["_raw"]
    bal = {b["account"]: b["solde"] for b in ledger.balances(con, eid, None, e)}
    S = lambda prefixes, only=None: sum(v for k, v in bal.items() if any(k.startswith(p) for p in prefixes) and (only is None or (only == "D" and v > 0) or (only == "C" and v < 0)))
    ca = g["ca"]
    clients = S(["411", "413", "416", "418"], "D")
    fournisseurs = -S(["401", "403", "404", "408"], "C")
    stocks = S(["3"], "D")
    autres_creances = S(["409", "42", "43", "44", "45", "46", "47", "486"], "D")
    dettes_exploit = fournisseurs - S(["42", "43", "44", "487"], "C")
    bfr = stocks + clients + autres_creances - dettes_exploit
    treso = S(["51", "53"]) 
    capitaux_propres = -S(["10", "11", "12", "13", "14"]) - sum(v for k, v in bal.items() if k[0] in "67")
    dettes_fin = -S(["16"]) - S(["519"], "C")
    actif_circ = stocks + clients + autres_creances + max(treso, 0)
    dettes_ct = dettes_exploit + max(-treso, 0)
    achats = g["cout_m"] + g["conso"]
    pct = lambda a, b: round(a / b * 100, 1) if b else None
    jours = lambda a, b: round(a / b * 365) if b else None
    ratios = [
        ("Taux de marge brute d'exploitation (EBE / CA)", pct(g["ebe"], ca), "%", "Rentabilité de l'activité avant amortissements et financement."),
        ("Taux de marge nette (résultat / CA)", pct(g["net"], ca), "%", "Part du chiffre d'affaires qui reste en bénéfice."),
        ("Taux de valeur ajoutée (VA / CA)", pct(g["va"], ca), "%", "Richesse créée par l'entreprise."),
        ("Poids des charges de personnel (personnel / VA)", pct(g["personnel"], g["va"]), "%", "Au-delà de 70-80 %, la rentabilité est fragile."),
        ("Délai moyen de paiement clients", jours(clients, ca * 1.2), "jours", "Plafond légal général : 60 jours date de facture."),
        ("Délai moyen de paiement fournisseurs", jours(fournisseurs, achats * 1.2), "jours", "Plafond légal général : 60 jours date de facture."),
        ("Besoin en fonds de roulement", E(bfr), "€", "Argent immobilisé par le cycle d'exploitation."),
        ("BFR en jours de CA", jours(bfr, ca), "jours", ""),
        ("Trésorerie nette", E(treso), "€", ""),
        ("Capitaux propres", E(capitaux_propres), "€", "Doivent rester supérieurs à la moitié du capital social (art. L223-42 / L225-248 C. com.)."),
        ("Autonomie financière (capitaux propres / total bilan)", pct(capitaux_propres, actif_circ + S(["2"]) ), "%", "Au-dessus de 20-25 %, la structure est jugée saine."),
        ("Endettement (dettes financières / capitaux propres)", pct(dettes_fin, capitaux_propres), "%", "Gearing : au-delà de 100 %, endettement élevé."),
        ("Liquidité générale (actif circulant / dettes court terme)", round(actif_circ / dettes_ct, 2) if dettes_ct else None, "x", "Supérieur à 1 : l'entreprise peut faire face à ses dettes à court terme."),
        ("Capacité de remboursement (dettes financières / CAF)", round(dettes_fin / g["caf"], 1) if g["caf"] > 0 else None, "années", "Les banques attendent généralement moins de 3-4 ans."),
    ]
    return {"annee": year, "ratios": [{"ratio": r, "valeur": v, "unite": u, "aide": a} for r, v, u, a in ratios], "seuil": breakeven(con, eid, year)}

VARIABLE = ("601", "602", "6031", "604", "607", "6037", "611", "624", "6257")

def breakeven(con, eid, year):
    f = _flows(con, eid, f"{year}-01-01", f"{year}-12-31")
    ca = -_s(f, ["70"])
    var = _s(f, VARIABLE)
    fixes = _s(f, ["6"], exclude=VARIABLE + ("695", "691"))
    mcv = ca - var
    if ca <= 0 or mcv <= 0:
        return {"seuil": None, "commentaire": "Données insuffisantes pour calculer le seuil de rentabilité."}
    taux = mcv / ca
    seuil = fixes / taux
    point_mort = round(seuil / ca * 365) if ca else None
    return {"chiffre_affaires": E(ca), "charges_variables": E(var), "charges_fixes": E(fixes), "taux_marge_cout_variable": round(taux * 100, 1),
            "seuil": E(round(seuil)), "point_mort_jours": point_mort, "marge_securite": E(round(ca - seuil)),
            "commentaire": (f"Seuil atteint en {point_mort} jours d'activité" if point_mort and point_mort <= 365 else "Seuil de rentabilité non atteint sur l'exercice")}

# ---------------- Trésorerie prévisionnelle ----------------
def _norm(label):
    return re.sub(r"\d+|\s+", " ", re.sub(r"[^A-Za-z ]", " ", label.upper())).strip()[:22]

def recurring(con, eid, months=6):
    """Détecte les opérations bancaires récurrentes (même libellé normalisé sur ≥ 3 mois)."""
    since = (dt.date.today().replace(day=1) - dt.timedelta(days=31 * months)).isoformat()
    groups = defaultdict(list)
    for r in con.execute("SELECT date,label,amount FROM bank_tx WHERE entity_id=? AND date>=?", (eid, since)):
        groups[_norm(r["label"])].append(r)
    out = []
    for k, rows in groups.items():
        ms = {r["date"][:7] for r in rows}
        if len(ms) >= 3:
            out.append({"libelle": k, "montant_mensuel": round(statistics.median(r["amount"] for r in rows)), "mois": len(ms)})
    return out

def cash_forecast(con, eid, months=12, start=None):
    start = dt.date.fromisoformat(start) if start else dt.date.today().replace(day=1)
    cash = ledger.solde(con, eid, "51") + ledger.solde(con, eid, "53")
    keys = []
    d = start
    for _ in range(months):
        keys.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    rows = {k: defaultdict(int) for k in keys}
    def put(month, cat, amt):
        m = month if month in rows else (keys[0] if month < keys[0] else None)
        if m:
            rows[m][cat] += amt
    for inv in con.execute("SELECT * FROM invoices WHERE entity_id=? AND status='open'", (eid,)):
        put(inv["due"][:7], "Encaissements clients" if inv["kind"] == "sale" else "Fournisseurs", inv["ttc"] if inv["kind"] == "sale" else -inv["ttc"])
    for q in con.execute("SELECT * FROM quotes WHERE entity_id=? AND status IN ('accepte','envoye')", (eid,)):
        prob = 1.0 if q["status"] == "accepte" else 0.4
        put((dt.date.fromisoformat(q["date"]) + dt.timedelta(days=60)).strftime("%Y-%m"), "Devis en cours (pondérés)", round(q["ttc"] * prob))
    last = con.execute("SELECT data FROM payslips WHERE entity_id=? ORDER BY period DESC LIMIT 50", (eid,)).fetchall()
    import json
    if last:
        period = json.loads(last[0]["data"])["periode"]
        cout = sum(json.loads(r["data"])["cout_employeur"] for r in last if json.loads(r["data"])["periode"] == period)
        for k in keys:
            rows[k]["Salaires et charges sociales"] -= ledger.cents(cout)
    for r in recurring(con, eid):
        if any(x in r["libelle"] for x in ("SALAIRE", "PAIE", "URSSAF")) and last:
            continue
        for k in keys:
            rows[k]["Récurrents : " + r["libelle"].title()[:24]] += r["montant_mensuel"]
    tva = ledger.solde(con, eid, "44571") + ledger.solde(con, eid, "44566") + ledger.solde(con, eid, "44551")
    if tva < 0:
        put(keys[0], "TVA à payer", tva)
    out, bal = [], cash
    for k in keys:
        flux = sum(rows[k].values())
        bal += flux
        out.append({"mois": k, "detail": {c: E(v) for c, v in rows[k].items() if v}, "flux": E(flux), "solde_fin": E(bal), "alerte": bal < 0})
    neg = next((o["mois"] for o in out if o["alerte"]), None)
    return {"tresorerie_actuelle": E(cash), "mois": out, "premier_mois_negatif": neg,
            "commentaire": (f"⚠ Trésorerie négative prévue en {neg} : anticipez (relances, découvert autorisé, report de dépenses)." if neg
                            else "Aucune tension de trésorerie prévue sur la période.")}

# ---------------- Budget ----------------
def set_budget(con, eid, year, account, annual_eur=None, monthly=None):
    vals = monthly or [ledger.cents(annual_eur) / 12] * 12
    for m, v in enumerate(vals, 1):
        con.execute("INSERT INTO budgets(entity_id,year,account,month,amount) VALUES(?,?,?,?,?) ON CONFLICT(entity_id,year,account,month) DO UPDATE SET amount=excluded.amount",
                    (eid, year, account, m, round(v)))

def budget_vs_actual(con, eid, year):
    out = []
    for acc, label in con.execute("""SELECT DISTINCT b.account, a.label FROM budgets b LEFT JOIN accounts a ON a.entity_id=b.entity_id AND a.code=b.account
                                     WHERE b.entity_id=? AND b.year=?""", (eid, year)).fetchall():
        bud = con.execute("SELECT SUM(amount) FROM budgets WHERE entity_id=? AND year=? AND account=?", (eid, year, acc)).fetchone()[0]
        real = sum(b["solde"] for b in ledger.balances(con, eid, f"{year}-01-01", f"{year}-12-31", acc, exclude_closing=True))
        real = -real if acc[0] == "7" else real
        out.append({"compte": acc, "libelle": label, "budget": E(bud), "reel": E(real), "ecart": E(real - bud), "taux": round(real / bud * 100, 1) if bud else None})
    return out
