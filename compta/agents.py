"""Agents IA spécialisés : un expert par outil.

Chaque agent a une expertise (consignes), un contexte chiffré propre à son domaine, des analyses proactives
(calculées localement, donc toujours disponibles) et un chat. Avec Claude, l'agent répond en expert à partir
de son contexte ; sans clé API, il répond avec ses analyses et ses règles.
"""
import json, datetime as dt
from . import ai, ledger, business, tiers, closing, analysis, tax, profile as P, db

E = ledger.euros
TODAY = lambda: dt.date.today().isoformat()

def _ins(niveau, titre, detail="", action=None):
    return {"niveau": niveau, "titre": titre, "detail": detail, "action": action}

# ---------------- Contextes et analyses par domaine ----------------
def banque(con, eid, y):
    pend = con.execute("SELECT COUNT(*), COALESCE(SUM(confidence<0.5),0) FROM bank_tx WHERE entity_id=? AND status='pending'", (eid,)).fetchone()
    att = ledger.solde(con, eid, "471")
    rec = analysis.recurring(con, eid)
    ins = []
    if pend[0]:
        ins.append(_ins("attention", f"{pend[0]} opération(s) à valider", f"dont {pend[1]} que l'IA n'a pas su classer avec certitude.", {"tab": "bank", "label": "Valider"}))
    if att:
        ins.append(_ins("attention", f"Compte d'attente : {ledger.fr(att)}", "Des opérations restent à recatégoriser avant la clôture.", {"tab": "jrn", "label": "Voir"}))
    if rec:
        tot = sum(r["montant_mensuel"] for r in rec if r["montant_mensuel"] < 0)
        ins.append(_ins("info", f"{len(rec)} prélèvement(s) récurrent(s) détecté(s)", f"Total mensuel : {ledger.fr(-tot)}. Vérifiez les abonnements inutilisés."))
    st = con.execute("SELECT date FROM bank_statements WHERE entity_id=? ORDER BY date DESC LIMIT 1", (eid,)).fetchone()
    if not st:
        ins.append(_ins("info", "Rapprochement bancaire jamais effectué", "Saisissez le solde de votre dernier relevé pour contrôler la concordance.", {"tab": "rappro", "label": "Rapprocher"}))
    return {"operations_a_valider": pend[0], "compte_attente": E(att), "recurrents": rec[:10]}, ins

def ventes(con, eid, y):
    ab = tiers.aged_balance(con, eid, "client")
    q = con.execute("SELECT COUNT(*), COALESCE(SUM(ttc),0) FROM quotes WHERE entity_id=? AND status='accepte'", (eid,)).fetchone()
    ins = []
    late = ab["total"]["total"] - ab["total"]["non échu"]
    if late:
        ins.append(_ins("attention", f"{ledger.fr(late)} de factures en retard", "Relancez en priorité les montants de plus de 60 jours.", {"tab": "inv", "label": "Relancer"}))
    for l in ab["lignes"][:3]:
        t = con.execute("SELECT id FROM tiers WHERE entity_id=? AND account=?", (eid, l["account"])).fetchone()
        sc = tiers.risk_score(con, eid, t[0]) if t else None
        if sc and sc["score"] < 50:
            ins.append(_ins("critique", f"Client à risque : {l['tiers']}", f"Retard moyen {sc['retard_moyen_jours']} jours. {sc['commentaire']}."))
    if q[0]:
        ins.append(_ins("info", f"{q[0]} devis accepté(s) non facturé(s)", f"{ledger.fr(q[1])} à facturer.", {"tab": "quotes", "label": "Facturer"}))
    return {"balance_agee": ab, "devis_acceptes": q[0]}, ins

def depenses(con, eid, y):
    n = con.execute("SELECT COUNT(*), COALESCE(SUM(ttc),0) FROM expenses WHERE entity_id=? AND status='a_valider'", (eid,)).fetchone()
    v = con.execute("SELECT COALESCE(SUM(ttc),0) FROM expenses WHERE entity_id=? AND status='validee'", (eid,)).fetchone()[0]
    ins = []
    if n[0]:
        ins.append(_ins("attention", f"{n[0]} note(s) de frais à valider", ledger.fr(n[1]), {"tab": "ndf", "label": "Valider"}))
    if v:
        ins.append(_ins("info", f"{ledger.fr(v)} à rembourser", "Notes validées en attente de remboursement.", {"tab": "ndf", "label": "Rembourser"}))
    for r in con.execute("""SELECT e.label, l.debit FROM lines l JOIN entries e ON e.id=l.entry_id WHERE e.entity_id=? AND l.debit>50000
                             AND l.account IN ('606','6063','628','615') AND e.date BETWEEN ? AND ?""", (eid, f"{y}-01-01", f"{y}-12-31")):
        ins.append(_ins("info", "Dépense à immobiliser ?", f"« {r['label']} » ({ledger.fr(r['debit'])} HT) : un bien durable de plus de 500 € HT s'amortit.", {"tab": "close", "label": "Immobiliser"}))
    return {"notes_a_valider": n[0], "a_rembourser": E(v)}, ins

def paie(con, eid, y):
    import json as j
    month = dt.date.today().strftime("%Y-%m")
    emps = con.execute("SELECT COUNT(*) FROM employees WHERE entity_id=? AND actif=1", (eid,)).fetchone()[0]
    done = con.execute("SELECT COUNT(*) FROM payslips WHERE entity_id=? AND period=?", (eid, month)).fetchone()[0]
    ins = []
    if emps and done < emps:
        ins.append(_ins("attention", f"Paie de {month} à établir", f"{emps - done} bulletin(s) restant(s).", {"tab": "pay", "label": "Faire la paie"}))
    from . import payroll
    smic = payroll.params(dt.date.today().year)["smic_mensuel"]
    for e in con.execute("SELECT prenom, nom, brut, heures FROM employees WHERE entity_id=? AND actif=1", (eid,)):
        if e["brut"] / 100 < smic * (e["heures"] or 151.67) / 151.67 - 0.01:
            ins.append(_ins("critique", f"Salaire inférieur au SMIC : {e['prenom']} {e['nom']}", f"{ledger.fr(e['brut'])} < {smic:.2f} € pour un temps plein."))
    cost = sum(j.loads(r[0])["cout_employeur"] for r in con.execute("SELECT data FROM payslips WHERE entity_id=? AND substr(period,1,4)=?", (eid, str(y))))
    return {"salaries_actifs": emps, "cout_employeur_annee": round(cost, 2)}, ins

def tva_agent(con, eid, y):
    ent = ledger.entity(con, eid)
    m = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    d = tax.ca3(con, eid, m.replace(day=1).isoformat(), m.isoformat())
    ins = []
    if ent["tva_regime"] == "franchise":
        ca = -ledger.solde(con, eid, "70", f"{y}-01-01", f"{y}-12-31") / 100
        if ca > 30000:
            ins.append(_ins("attention", "Seuil de franchise de TVA en approche", f"CA {y} : {ca:,.0f} €. Au-delà du seuil, la TVA est due dès le dépassement.".replace(",", " ")))
    elif d["a_payer"]:
        ins.append(_ins("info", f"TVA de {m.strftime('%m/%Y')} : {ledger.fr(ledger.cents(d['a_payer']))} à déclarer", "Échéance autour du 19 du mois.", {"tab": "decl", "label": "Déclarer"}))
    elif d["credit"]:
        ins.append(_ins("info", f"Crédit de TVA de {ledger.fr(ledger.cents(d['credit']))}", "Reportable, ou remboursable (formulaire 3519) au-delà de 150 € en fin de trimestre / 760 € en cours d'année."))
    nointra = con.execute("SELECT COUNT(*) FROM tiers WHERE entity_id=? AND type='client' AND pays!='FR' AND (tva_intra IS NULL OR tva_intra='')", (eid,)).fetchone()[0]
    if nointra:
        ins.append(_ins("attention", f"{nointra} client(s) étranger(s) sans numéro de TVA", "Obligatoire pour facturer sans TVA en intracommunautaire.", {"tab": "tiers", "label": "Compléter"}))
    return {"derniere_ca3": d}, ins

def fiscal_pro(con, eid, y):
    ent = ledger.entity(con, eid)
    res = ledger.income_statement(con, eid, f"{y}-01-01", f"{y}-12-31")["resultat"]
    isr = tax.impot_societes(res / 100, True, y)
    ins = []
    if ent["legal_form"] in ("SAS", "SASU", "SARL", "EURL"):
        if res > 4250000:
            ins.append(_ins("info", "Bénéfice au-delà du taux réduit de 15 %", "Au-delà de 42 500 €, l'IS passe à 25 % : envisagez rémunération, investissements ou épargne salariale."))
        if isr.get("acomptes_trimestriels"):
            ins.append(_ins("info", f"Acomptes d'IS : {isr['acomptes_trimestriels']} € par trimestre", "15 mars, 15 juin, 15 septembre, 15 décembre."))
    cp = analysis.ratios(con, eid, y)
    capres = next((r for r in cp["ratios"] if r["ratio"] == "Capitaux propres"), None)
    capital = -ledger.solde(con, eid, "101") / 100
    if capres and capital and capres["valeur"] < capital / 2:
        ins.append(_ins("critique", "Capitaux propres inférieurs à la moitié du capital", "Obligation de consulter les associés dans les 4 mois suivant l'approbation des comptes."))
    return {"resultat": E(res), "impot_societes": isr}, ins

def tresorerie(con, eid, y):
    f = analysis.cash_forecast(con, eid, 6)
    ins = [_ins("critique" if f["premier_mois_negatif"] else "ok", "Trésorerie prévisionnelle", f["commentaire"], {"tab": "analyse", "label": "Voir la prévision"})]
    return {"prevision": f}, ins

def cloture(con, eid, y):
    ins = []
    sug = closing.suggest_regularisations(con, eid, y)
    if sug:
        ins.append(_ins("info", f"{len(sug)} régularisation(s) de fin d'exercice suggérée(s)", "; ".join(s["libelle"] for s in sug[:3]), {"tab": "close", "label": "Examiner"}))
    nl = con.execute("""SELECT COUNT(*) FROM lines l JOIN entries e ON e.id=l.entry_id WHERE e.entity_id=? AND (l.account LIKE '411%' OR l.account LIKE '401%')
                        AND length(l.account)>3 AND l.lettrage IS NULL""", (eid,)).fetchone()[0]
    if nl:
        ins.append(_ins("info", f"{nl} ligne(s) de tiers non lettrée(s)", "Lancez le lettrage automatique.", {"tab": "tiers", "label": "Lettrer"}))
    for a in business.audit(con, eid, y):
        if a["niveau"] in ("critique", "attention"):
            ins.append(_ins(a["niveau"], a["message"]))
    return {"suggestions": sug}, ins

def impots_perso(con, eid, y):
    from . import tax_agent
    d = tax_agent.build(con, eid, y)
    ins = [_ins("ok" if d["statut"] == "prete" else "attention", f"Déclaration {y} : {d['completude']} % des justificatifs",
                f"Impôt estimé {d['calcul']['total_a_payer']} € · solde {d['calcul']['solde']} €.", {"tab": "tax", "label": "Ouvrir"})]
    for o in d["optimisations"]:
        if o["gain"] and o["applique"]:
            ins.append(_ins("ok", f"Optimisation : {o['titre']}", f"Économie estimée {o['gain']} €."))
    for c in d["controles"]:
        ins.append(_ins("critique" if c["niveau"] == "bloquant" else c["niveau"], c["message"]))
    return {"declaration": {k: d[k] for k in ("statut", "completude", "parts", "optimisations", "controles", "pieces")}, "calcul": d["calcul"]}, ins

def comptable(con, eid, y):
    ctx = business.context(con, eid, y)
    ins = [_ins(a["niveau"] if a["niveau"] != "ok" else "ok", a["message"]) for a in business.audit(con, eid, y)]
    return ctx, ins

def conseil(con, eid, y):
    s = analysis.sig(con, eid, y)
    r = analysis.ratios(con, eid, y)
    ins = []
    g = s["_raw"]
    if g["ca"]:
        ins.append(_ins("info", f"EBE : {ledger.fr(g['ebe'])} ({round(g['ebe'] / g['ca'] * 100, 1)} % du CA)"))
    if r["seuil"].get("point_mort_jours"):
        ins.append(_ins("info", "Seuil de rentabilité", r["seuil"]["commentaire"]))
    return {"sig": [l for l in s["lignes"]], "ratios": r["ratios"]}, ins

AGENTS = {
    "comptable": ("Expert-comptable", "Tenue, révision et cohérence de la comptabilité.", comptable,
                  "Tu es un expert-comptable français (PCG, règles de révision). Tu expliques simplement et tu proposes des écritures précises (comptes, débit/crédit).",
                  ["Mes comptes sont-ils prêts pour la clôture ?", "Quelles écritures dois-je passer ?", "Explique-moi mon bilan simplement"]),
    "banque": ("Agent Banque", "Catégorisation, rapprochement, abonnements.", banque,
               "Tu es spécialiste de la tenue bancaire : catégorisation PCG, TVA récupérable, rapprochement, détection d'anomalies et d'abonnements.",
               ["Quels abonnements puis-je supprimer ?", "Pourquoi cette opération est-elle en compte d'attente ?"]),
    "ventes": ("Agent Ventes & recouvrement", "Devis, factures, relances, risque client.", ventes,
               "Tu es spécialiste du cycle client : facturation conforme, conditions de paiement (L441-10 C. com.), relances, recouvrement amiable et judiciaire.",
               ["Quels clients relancer en priorité ?", "Comment réduire mes délais de paiement ?"]),
    "depenses": ("Agent Dépenses", "Achats, notes de frais, TVA récupérable.", depenses,
                 "Tu es spécialiste des charges : déductibilité fiscale, TVA récupérable (art. 206 annexe II CGI), notes de frais, immobilisations.",
                 ["Cette dépense est-elle déductible ?", "Puis-je récupérer la TVA sur le carburant ?"]),
    "paie": ("Agent Paie", "Bulletins, charges, DSN, droit social.", paie,
             "Tu es gestionnaire de paie français : cotisations, réduction générale, PAS, DSN, Code du travail. Tu signales les risques sociaux.",
             ["Combien me coûte un salarié à 2 500 € net ?", "Quelles sont mes échéances DSN ?"]),
    "tva": ("Agent TVA", "Déclarations, régimes, international.", tva_agent,
            "Tu es expert TVA française et européenne : exigibilité, taux, autoliquidation, intracommunautaire, CA3/CA12, crédit de TVA.",
            ["Dois-je facturer la TVA à un client belge ?", "Comment récupérer mon crédit de TVA ?"]),
    "fiscal": ("Agent Fiscal entreprise", "IS, liasse, optimisation dirigeant.", fiscal_pro,
               "Tu es fiscaliste d'entreprise : IS, liasse 2033/2065, réintégrations, rémunération du dirigeant, dividendes, CFE.",
               ["Salaire ou dividendes : que me conseilles-tu ?", "Comment réduire mon IS légalement ?"]),
    "tresorerie": ("Agent Trésorerie", "Prévisions, BFR, alertes.", tresorerie,
                   "Tu es trésorier d'entreprise : prévision de trésorerie, BFR, financement court terme, négociation bancaire.",
                   ["Vais-je manquer de trésorerie ?", "Comment améliorer mon BFR ?"]),
    "cloture": ("Agent Révision & clôture", "Cut-off, lettrage, contrôles de fin d'exercice.", cloture,
                "Tu es réviseur comptable : cycle de clôture, régularisations (CCA, PCA, FNP, FAE, provisions), lettrage, rapprochement, contrôles de cohérence.",
                ["Que me reste-t-il à faire avant la clôture ?", "Explique les charges constatées d'avance"]),
    "conseil": ("Agent Analyse & conseil", "SIG, ratios, rentabilité.", conseil,
                "Tu es contrôleur de gestion : SIG, ratios, seuil de rentabilité, recommandations concrètes et chiffrées.",
                ["Mon entreprise est-elle rentable ?", "Quels ratios dois-je surveiller ?"]),
    "impots": ("Agent Impôts", "Déclaration de revenus du foyer, optimisations.", impots_perso,
               "Tu es fiscaliste des particuliers (CGI, BOFiP). Tu prépares la déclaration de revenus et proposes des optimisations légales chiffrées.",
               ["Comment payer moins d'impôt légalement ?", "Quels documents dois-je fournir ?", "Frais réels ou 10 % ?"]),
}
TAB_AGENT = {"dash": "comptable", "bank": "banque", "rappro": "banque", "inv": "ventes", "quotes": "ventes", "tiers": "ventes", "ndf": "depenses",
             "pay": "paie", "tva": "tva", "decl": "fiscal", "tax": "fiscal", "close": "cloture", "jrn": "comptable", "rep": "conseil",
             "analyse": "tresorerie", "ai": "comptable"}

def for_tab(kind, tab):
    if kind == "particulier":
        return {"tax": "impots", "impots": "impots", "bank": "banque", "dash": "impots"}.get(tab, "comptable")
    return TAB_AGENT.get(tab, "comptable")

def run(con, eid, name, year):
    title, desc, fn, _, sugg = AGENTS[name]
    try:
        ctx, ins = fn(con, eid, year)
    except Exception as e:  # un agent ne doit jamais bloquer l'interface
        ctx, ins = {}, [_ins("info", "Analyse indisponible", str(e)[:200])]
    return {"agent": name, "titre": title, "description": desc, "analyses": ins, "suggestions": sugg, "ia": ai.enabled(), "_ctx": ctx}

def ask(con, eid, name, year, question, history=None):
    r = run(con, eid, name, year)
    persona = AGENTS[name][3]
    p, _ = P.get(con, eid)
    sys = (persona + " Tu fais partie du logiciel ComptaIA et tu parles à son utilisateur (pas forcément expert) : réponds en français, clairement, "
           "avec des chiffres tirés du contexte fourni et des étapes concrètes dans le logiciel. Cite la règle (CGI, BOFiP, Code de commerce) quand c'est utile. "
           "N'invente jamais de chiffres absents du contexte ; signale ce qu'il faut vérifier.")
    payload = {"profil": {k: v for k, v in p.items() if not k.startswith("_")}, "contexte": r["_ctx"], "analyses": r["analyses"],
               "historique": (history or [])[-6:], "question": question}
    ans = ai.llm(sys, json.dumps(payload, ensure_ascii=False, default=str), 1500)
    if ans:
        return {"answer": ans, "mode": "ia"}
    # Mode local : base de connaissances experte puis analyses de l'agent
    kb = kb_answer(name, question, r["_ctx"])
    if kb:
        extra = [f"• {i['titre']}" for i in r["analyses"][:3] if i["niveau"] in ("critique", "attention")]
        return {"answer": kb + (("\n\nÀ surveiller dans votre dossier :\n" + "\n".join(extra)) if extra else ""), "mode": "regles"}
    lines = [f"{AGENTS[name][0]} — mode hors ligne (sans clé ANTHROPIC_API_KEY). Voici ce que j'observe dans votre dossier :"]
    for i in r["analyses"][:6]:
        lines.append(f"• {i['titre']}" + (f" — {i['detail']}" if i["detail"] else ""))
    if len(lines) == 1:
        lines.append("• Rien d'anormal détecté dans mon domaine.")
    fb = ai.assistant(question, business.context(con, eid, year))
    if fb["answer"] and not fb["answer"].startswith("Mode hors-ligne"):
        lines.append("\n" + fb["answer"])
    return {"answer": "\n".join(lines), "mode": "regles"}

# ---------------- Base de connaissances (mode hors ligne) ----------------
def _net_to_brut(net):
    from . import payroll
    lo, hi = net, net * 2
    for _ in range(40):
        mid = (lo + hi) / 2
        if payroll.compute({"brut": mid}, dt.date.today().strftime("%Y-%m"))["net_social"] < net:
            lo = mid
        else:
            hi = mid
    return payroll.compute({"brut": round(hi, 2)}, dt.date.today().strftime("%Y-%m"))

def _cout_salarie(q, ctx):
    import re
    m = re.search(r"(\d[\d\s]{2,})\s*(?:€|euros?)?\s*(net|brut)?", q.replace(" ", " "))
    if not m:
        return None
    v = float(m.group(1).replace(" ", ""))
    from . import payroll
    b = _net_to_brut(v) if (m.group(2) or "net") == "net" else payroll.compute({"brut": v}, dt.date.today().strftime("%Y-%m"))
    f = lambda x, d=2: f"{x:,.{d}f}".replace(",", "\u202f").replace(".", ",") + " €"
    return (f"Pour {f(v, 0)} {(m.group(2) or 'net')} par mois (non-cadre, temps plein, entreprise de moins de 11 salariés) :\n"
            f"• salaire brut : {f(b['brut'])}\n• cotisations salariales : {f(b['total_salarial'])}\n• cotisations patronales (après réduction générale) : {f(b['total_patronal'])}\n"
            f"• coût total employeur : {f(b['cout_employeur'])} par mois, soit {f(b['cout_employeur'] * 12, 0)} par an.\n"
            "Simulation avec les taux paramétrés dans le logiciel ; ajoutez mutuelle, prévoyance et tickets-restaurant le cas échéant.")

KB = [
    ("tva", ["belge", "allemand", "espagnol", "italien", "europe", "ue", "intracom", "etranger"],
     lambda q, c: "Client professionnel dans l'UE (B2B) : vous facturez **hors taxe**, avec la mention « Autoliquidation — art. 283-2 du CGI » "
                  "et le numéro de TVA intracommunautaire du client (vérifiez-le sur le site VIES). Pour des services, déposez chaque mois la "
                  "déclaration européenne de services (DES) sur douane.gouv.fr ; pour des biens, l'état récapitulatif. Client particulier (B2C) : "
                  "TVA française, sauf ventes à distance / services électroniques au-delà de 10 000 € par an dans l'UE (guichet OSS). "
                  "Dans le logiciel : facture › opération « UE services » ou « UE biens »."),
    ("tva", ["credit", "rembours"], lambda q, c: "Un crédit de TVA est reportable sur les déclarations suivantes. Remboursement possible avec le formulaire 3519 : "
                  "annuellement si ≥ 150 €, ou trimestriellement si ≥ 760 € (régime réel normal). En régime simplifié, la demande se fait avec la CA12."),
    ("depenses", ["carburant", "essence", "gazole", "diesel"], lambda q, c: "TVA sur carburant : gazole et essence récupérables à 80 % pour un véhicule de tourisme, "
                  "100 % pour un utilitaire. Pas de TVA récupérable sur l'achat ou la location d'une voiture de tourisme (sauf exceptions : taxis, auto-écoles…)."),
    ("depenses", ["deductible", "deduire", "deduction"], lambda q, c: "Une dépense est déductible si elle est engagée dans l'intérêt de l'entreprise, justifiée par une "
                  "facture à son nom, correspond à une charge effective et n'est pas excessive (art. 39-1 du CGI). Exclus notamment : amendes, dépenses "
                  "personnelles, cadeaux au-delà de 73 € TTC par bénéficiaire et par an pour la TVA. Un bien durable de plus de 500 € HT s'amortit."),
    ("depenses", ["restaurant", "repas"], lambda q, c: "Repas d'affaires (clients, prospects) : déductibles et TVA récupérable (10 %), avec la facture et le nom des invités. "
                  "Repas seul du dirigeant d'entreprise individuelle : déductible au-delà de la valeur d'un repas à domicile et dans une limite annuelle fixée chaque année."),
    ("fiscal", ["salaire", "dividende", "remuneration"], lambda q, c: "Salaire du dirigeant : déductible du résultat (il diminue l'IS), mais supporte des cotisations élevées "
                  "(≈ 75-80 % du net en SAS, ≈ 45 % en gérance majoritaire TNS) et ouvre des droits (retraite, prévoyance). Dividendes : versés après IS (15 % puis 25 %), "
                  "imposés au PFU de 30 % ; en SAS/SASU, pas de cotisations sociales ; en SARL/EURL avec gérant majoritaire, la part au-delà de 10 % du capital "
                  "et des comptes courants est soumise aux cotisations TNS. Le bon équilibre dépend de votre TMI et de vos besoins de protection sociale : "
                  "l'agent peut simuler si Claude est connecté."),
    ("fiscal", ["reduire", "baisser", "optimis", "moins d'is", "moins d impot"], lambda q, c: "Leviers légaux pour réduire l'IS : profiter du taux réduit de 15 % jusqu'à 42 500 € "
                  "(PME, capital entièrement libéré), rémunérer le dirigeant, investir (amortissements), constituer les provisions justifiées, mettre en place "
                  "intéressement / abondement PEE (déductibles), mécénat (réduction de 60 %), crédit d'impôt recherche ou innovation selon l'activité."),
    ("ventes", ["delai", "retard", "relance", "payer plus vite", "recouvr"], lambda q, c: "Délais légaux : 60 jours à compter de la facture ou 45 jours fin de mois (art. L441-10 C. com.). "
                  "Mentionnez sur la facture les pénalités de retard (3 fois le taux légal minimum) et l'indemnité de 40 €. Pour accélérer : acompte à la commande, "
                  "paiement par lien ou prélèvement, relances à J+1, J+15 et J+30 (automatiques dans l'onglet Factures), puis injonction de payer."),
    ("paie", ["coute", "cout", "embaucher", "net"], lambda q, c: _cout_salarie(q, c)),
    ("paie", ["dsn", "echeance"], lambda q, c: "DSN mensuelle : au plus tard le 5 du mois suivant (50 salariés et plus) ou le 15 (moins de 50), sur net-entreprises.fr. "
                  "Elle déclare salaires, cotisations et prélèvement à la source. Le fichier est généré dans l'onglet Paie."),
    ("cloture", ["avance", "cca", "constatee"], lambda q, c: "Charge constatée d'avance : une dépense payée cette année mais qui concerne en partie l'année suivante "
                  "(ex. assurance annuelle payée en octobre). On retire du résultat la part de l'an prochain : débit 486, crédit du compte de charge, "
                  "puis extourne automatique au 1er janvier. L'agent Révision les détecte et les passe pour vous."),
    ("cloture", ["cloture", "reste", "avant"], lambda q, c: "Check-list de clôture : 1) valider toutes les opérations bancaires et vider le compte d'attente ; 2) rapprochement bancaire au 31/12 ; "
                  "3) lettrer clients et fournisseurs ; 4) régularisations (CCA, PCA, factures non parvenues, à établir, congés payés) ; 5) amortissements ; "
                  "6) dépréciation des créances douteuses ; 7) TVA : concordance entre déclarations et comptes 445 ; 8) IS ; 9) clôture et liasse."),
    ("comptable", ["bilan"], lambda q, c: "Le bilan est une photo de l'entreprise à une date : à gauche (actif) ce qu'elle possède (matériel, créances clients, banque) ; "
                  "à droite (passif) comment c'est financé (capital, bénéfices accumulés, dettes). Les deux côtés sont toujours égaux. Le compte de résultat, "
                  "lui, est le film de l'année : produits − charges = bénéfice."),
    ("tresorerie", ["bfr", "fonds de roulement"], lambda q, c: "Le BFR est l'argent bloqué dans le cycle d'exploitation (créances clients + stocks − dettes fournisseurs et fiscales). "
                  "Pour le réduire : facturer plus vite, demander des acomptes, raccourcir les délais clients, négocier des délais fournisseurs, réduire les stocks."),
    ("impots", ["moins", "reduire", "baisser", "optimis", "economis"], lambda q, c: "Leviers légaux pour le foyer : versements sur un PER (déductibles), dons (66 % ou 75 % de réduction), "
                  "emploi à domicile et garde d'enfants (crédit de 50 %), frais réels si supérieurs à 10 %, option pour le barème des revenus de capitaux si votre "
                  "tranche est basse, régime réel foncier en cas de travaux ou d'intérêts importants, rattachement des enfants majeurs ou pension alimentaire. "
                  "L'agent applique automatiquement ceux qui vous sont favorables."),
    ("impots", ["10 %", "frais reels", "frais réels", "10%"], lambda q, c: "L'abattement de 10 % est automatique. Les frais réels (trajets au barème kilométrique — 40 km "
                  "aller maximum sauf justification —, repas, télétravail, formation) sont intéressants s'ils dépassent ces 10 %. L'agent compare les deux à partir de votre profil."),
    ("impots", ["document", "piece", "fournir", "justificatif"], lambda q, c: "Pièces utiles : " + "; ".join(x["piece"] for x in (c.get("declaration") or {}).get("pieces", [])) if c.get("declaration") else None),
]

def kb_answer(name, question, ctx):
    q = P._norm(question)
    best, score = None, 0
    for agent, kws, fn in KB:
        s = sum(1 for k in kws if P._norm(k) in q) + (0.5 if agent == name else 0)
        if s > score and s >= 1:
            best, score = fn, s
    if best:
        try:
            return best(question, ctx)
        except Exception:
            return None
    return None
