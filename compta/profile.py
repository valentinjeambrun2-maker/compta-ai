"""Profil fiscal et entretien d'accueil conduit par l'IA.

À la création d'un dossier, l'IA mène un entretien pour connaître la situation de l'utilisateur. Les réponses
(libres ou guidées) sont transformées en un profil structuré, réutilisé chaque année pour préparer les
déclarations, calculer les échéances et paramétrer le dossier.

Deux modes d'extraction :
  - Claude : comprend une réponse libre (« marié, deux enfants nés en 2015 et 2019, je suis salarié ») et
    remplit plusieurs champs d'un coup, puis formule la question suivante de façon naturelle ;
  - règles locales : analyse des réponses courantes (situation, enfants, années, montants, oui/non).
"""
import json, re, datetime as dt
from . import ai, ledger, db

Y = dt.date.today().year

def _q(id, text, type_, help_="", options=None, when=None, kind="particulier", section="", unit=None, placeholder=None):
    return {"id": id, "text": text, "type": type_, "help": help_, "options": options or [], "when": when or (lambda p: True),
            "kind": kind, "section": section, "unit": unit, "placeholder": placeholder}

yes = lambda k: (lambda p: p.get(k) is True)
has = lambda k, *vals: (lambda p: p.get(k) in vals)
couple = lambda p: p.get("situation") in ("marie", "pacse")

SITUATIONS = [("celibataire", "Célibataire"), ("marie", "Marié·e"), ("pacse", "Pacsé·e"), ("union_libre", "En concubinage"),
              ("divorce", "Divorcé·e / séparé·e"), ("veuf", "Veuf·ve")]
ACTIVITES = [("salarie", "Salarié·e"), ("independant", "Indépendant·e / micro-entrepreneur"), ("dirigeant", "Dirigeant·e de société"),
             ("retraite", "Retraité·e"), ("chomage", "Demandeur d'emploi"), ("etudiant", "Étudiant·e"), ("sans", "Sans activité")]

QUESTIONS = [
    # ---------------- Particulier : foyer
    _q("prenom", "Pour commencer, comment vous appelez-vous ?", "text", section="Foyer", placeholder="Votre prénom"),
    _q("naissance", "Quelle est votre année de naissance ?", "number", "Certaines règles dépendent de l'âge (abattement des plus de 65 ans, rattachement…).", section="Foyer"),
    _q("situation", "Quelle est votre situation familiale au 31 décembre ?", "choice", "Elle détermine le nombre de parts et le type de déclaration.", SITUATIONS, section="Foyer"),
    _q("situation_changement", "Votre situation a-t-elle changé cette année (mariage, PACS, divorce, décès) ?", "yesno",
       "L'année d'un mariage ou d'un PACS, vous pouvez choisir une imposition commune ou séparée ; l'IA comparera les deux.", section="Foyer"),
    _q("conjoint_prenom", "Quel est le prénom de votre conjoint·e ?", "text", when=couple, section="Foyer"),
    _q("conjoint_naissance", "Son année de naissance ?", "number", when=couple, section="Foyer"),
    _q("enfants", "Combien d'enfants mineurs avez-vous à charge ?", "number", "Chaque enfant ajoute une demi-part (une part entière à partir du troisième).", section="Foyer"),
    _q("enfants_naissances", "Leurs années de naissance ? (séparées par des virgules)", "text", "Sert à la garde des moins de 6 ans et aux frais de scolarité.",
       when=lambda p: (p.get("enfants") or 0) > 0, section="Foyer", placeholder="2015, 2019"),
    _q("garde_alternee", "Certains enfants sont-ils en résidence alternée ?", "yesno", "En résidence alternée, l'enfant compte pour un quart de part.",
       when=lambda p: (p.get("enfants") or 0) > 0, section="Foyer"),
    _q("parent_isole", "Vivez-vous seul·e avec vos enfants ?", "yesno", "Case T : demi-part supplémentaire pour les parents isolés.",
       when=lambda p: (p.get("enfants") or 0) > 0 and not couple(p) and p.get("situation") != "union_libre", section="Foyer"),
    _q("enfants_majeurs", "Avez-vous des enfants majeurs (moins de 21 ans, ou moins de 25 ans s'ils étudient) que vous souhaitez rattacher ?", "number",
       "Le rattachement donne une demi-part ; sinon une pension alimentaire peut être déduite. L'IA comparera.", section="Foyer"),
    _q("invalidite", "Vous ou votre conjoint·e êtes-vous titulaire d'une carte d'invalidité (≥ 80 %) ?", "yesno", "Demi-part supplémentaire (cases P et F).", section="Foyer"),
    _q("departement", "Dans quel département habitez-vous ?", "text", "Pour connaître votre date limite de déclaration en ligne.", section="Foyer", placeholder="69"),
    _q("logement", "Vous êtes…", "choice", options=[("proprietaire", "Propriétaire de votre résidence principale"), ("locataire", "Locataire"), ("heberge", "Hébergé·e")], section="Foyer"),
    # ---------------- Revenus d'activité
    _q("activite", "Quelle est votre activité principale ?", "choice", options=ACTIVITES, section="Revenus"),
    _q("conjoint_activite", "Et celle de votre conjoint·e ?", "choice", options=ACTIVITES, when=couple, section="Revenus"),
    _q("salaire_annuel", "Quel est votre salaire net imposable annuel (approximatif) ?", "number",
       "Il figure sur votre bulletin de décembre (« net imposable cumulé »). L'IA le remplacera par le montant exact si vous importez le bulletin.",
       when=has("activite", "salarie", "dirigeant"), section="Revenus", unit="€"),
    _q("conjoint_salaire", "Et celui de votre conjoint·e ?", "number", when=lambda p: couple(p) and p.get("conjoint_activite") in ("salarie", "dirigeant"), section="Revenus", unit="€"),
    _q("trajet_km", "Quelle distance parcourez-vous entre domicile et travail (aller simple, en km) ?", "number",
       "Si vos frais réels dépassent la déduction forfaitaire de 10 %, l'IA les déclarera à la place.",
       when=has("activite", "salarie", "dirigeant"), section="Revenus", unit="km"),
    _q("trajet_cv", "Puissance fiscale de votre véhicule ?", "choice", options=[("3", "3 CV ou moins"), ("4", "4 CV"), ("5", "5 CV"), ("6", "6 CV"), ("7", "7 CV et plus"), ("0", "Pas de véhicule")],
       when=lambda p: (p.get("trajet_km") or 0) > 0, section="Revenus"),
    _q("teletravail_jours", "Combien de jours par semaine êtes-vous en télétravail ?", "number", "Réduit les trajets et ouvre droit à une allocation forfaitaire de frais.",
       when=has("activite", "salarie"), section="Revenus"),
    _q("micro_type", "Quel est votre régime d'indépendant ?", "choice",
       options=[("micro_bnc", "Micro-BNC (profession libérale)"), ("micro_bic_service", "Micro-BIC prestations de services"),
                ("micro_bic_vente", "Micro-BIC vente de marchandises"), ("reel", "Régime réel (déclaration 2031/2035)")],
       when=lambda p: p.get("activite") == "independant" or p.get("conjoint_activite") == "independant", section="Revenus"),
    _q("micro_ca", "Chiffre d'affaires annuel de cette activité ?", "number", when=lambda p: p.get("micro_type", "").startswith("micro"), section="Revenus", unit="€"),
    _q("versement_liberatoire", "Avez-vous opté pour le versement libératoire de l'impôt ?", "yesno",
       "Si oui, le chiffre d'affaires est déclaré mais n'est pas réimposé au barème.", when=lambda p: p.get("micro_type", "").startswith("micro"), section="Revenus"),
    _q("pension_retraite", "Montant annuel de vos pensions de retraite ?", "number", when=lambda p: "retraite" in (p.get("activite"), p.get("conjoint_activite")), section="Revenus", unit="€"),
    _q("chomage_montant", "Montant annuel des allocations chômage perçues ?", "number", when=lambda p: "chomage" in (p.get("activite"), p.get("conjoint_activite")), section="Revenus", unit="€"),
    # ---------------- Patrimoine
    _q("immobilier_locatif", "Louez-vous un ou plusieurs biens immobiliers ?", "yesno", section="Patrimoine"),
    _q("location_type", "Ces locations sont…", "choice", options=[("nue", "Vides (location nue)"), ("meublee", "Meublées (LMNP)"), ("les_deux", "Les deux")],
       when=yes("immobilier_locatif"), section="Patrimoine"),
    _q("loyers_annuels", "Montant total des loyers encaissés sur l'année ?", "number", when=yes("immobilier_locatif"), section="Patrimoine", unit="€"),
    _q("credit_immo_locatif", "Ces biens sont-ils financés par un crédit ?", "yesno", "Les intérêts d'emprunt sont déductibles au régime réel.", when=yes("immobilier_locatif"), section="Patrimoine"),
    _q("interets_annuels", "Montant annuel des intérêts d'emprunt ?", "number", when=yes("credit_immo_locatif"), section="Patrimoine", unit="€"),
    _q("charges_foncieres", "Charges annuelles (taxe foncière, assurance, copropriété, gestion, travaux) ?", "number",
       "L'IA comparera micro-foncier (abattement 30 %) et régime réel.", when=yes("immobilier_locatif"), section="Patrimoine", unit="€"),
    _q("placements", "Quels placements détenez-vous ?", "multi", "Chaque placement a sa propre fiscalité ; l'IA saura quels documents vous demander.",
       options=[("livrets", "Livrets réglementés"), ("pea", "PEA"), ("assurance_vie", "Assurance-vie"), ("cto", "Compte-titres"), ("crypto", "Cryptoactifs"),
                ("scpi", "SCPI"), ("etranger", "Compte ou contrat à l'étranger"), ("aucun", "Aucun")], section="Patrimoine"),
    _q("dividendes", "Montant annuel des dividendes et intérêts perçus (hors livrets) ?", "number", "Figure sur l'IFU envoyé par votre banque en février.",
       when=lambda p: any(x in (p.get("placements") or []) for x in ("cto", "scpi", "pea")), section="Patrimoine", unit="€"),
    _q("crypto_cessions", "Avez-vous vendu des cryptoactifs contre des euros cette année ?", "yesno", "Les plus-values se déclarent sur le formulaire 2086.",
       when=lambda p: "crypto" in (p.get("placements") or []), section="Patrimoine"),
    _q("comptes_etrangers", "Combien de comptes (bancaires, crypto, assurance-vie) détenez-vous à l'étranger ?", "number",
       "Leur déclaration (formulaire 3916) est obligatoire : 1 500 € d'amende par compte oublié.", when=lambda p: "etranger" in (p.get("placements") or []) or "crypto" in (p.get("placements") or []), section="Patrimoine"),
    # ---------------- Charges, réductions et crédits
    _q("per_versements", "Versements annuels sur un plan d'épargne retraite (PER) ?", "number", "Déductibles de votre revenu imposable, dans un plafond.", section="Réductions", unit="€"),
    _q("dons_annuels", "Montant de vos dons annuels à des associations ?", "number", "Réduction de 66 % (75 % pour l'aide aux personnes en difficulté).", section="Réductions", unit="€"),
    _q("dons_aide", "Dont dons aux associations d'aide aux personnes en difficulté (Restos du cœur, Secours populaire…) ?", "number", when=lambda p: (p.get("dons_annuels") or 0) > 0, section="Réductions", unit="€"),
    _q("emploi_domicile", "Dépenses annuelles pour un emploi à domicile (ménage, jardinage, soutien scolaire) ?", "number", "Crédit d'impôt de 50 %.", section="Réductions", unit="€"),
    _q("garde_montant", "Frais de garde (crèche, assistante maternelle) pour vos enfants de moins de 6 ans ?", "number", "Crédit d'impôt de 50 %, aides CAF déduites.",
       when=lambda p: any(Y - int(a) < 7 for a in re.findall(r"\d{4}", str(p.get("enfants_naissances") or ""))), section="Réductions", unit="€"),
    _q("pension_versee", "Versez-vous une pension alimentaire (enfant majeur, ex-conjoint, parent) ?", "number", "Déductible, dans certaines limites.", section="Réductions", unit="€/an"),
    _q("ehpad", "Avez-vous des frais d'hébergement en EHPAD (pour vous ou votre conjoint) ?", "number", "Réduction de 25 % jusqu'à 10 000 € de dépenses.", section="Réductions", unit="€"),
    _q("taux_pas", "Quel est votre taux de prélèvement à la source actuel ?", "number", "Visible dans votre espace impots.gouv.fr ; sert à estimer le solde à payer ou le remboursement.", section="Prélèvement à la source", unit="%"),
    _q("numero_fiscal", "Votre numéro fiscal (13 chiffres, facultatif) ?", "text", "Utilisé seulement si votre déclaration est télétransmise par un tiers déclarant (expert-comptable).", section="Prélèvement à la source"),
    # ---------------- Entreprise
    _q("activite_desc", "Décrivez votre activité en une phrase.", "text", "L'IA en déduit la nature des revenus (BIC/BNC), le code d'activité probable et les règles de TVA.", kind="entreprise", section="Entreprise", placeholder="Agence de conseil en marketing digital"),
    _q("forme", "Quelle est la forme juridique ?", "choice", options=[(x, x) for x in ("SASU", "SAS", "SARL", "EURL", "EI", "Micro-entreprise", "SCI")], kind="entreprise", section="Entreprise"),
    _q("date_creation", "Date de création de l'entreprise ?", "date", kind="entreprise", section="Entreprise"),
    _q("cloture", "Date de clôture de l'exercice ?", "choice", options=[("12-31", "31 décembre"), ("06-30", "30 juin"), ("03-31", "31 mars"), ("09-30", "30 septembre"), ("autre", "Autre")], kind="entreprise", section="Entreprise"),
    _q("regime_fiscal", "Votre entreprise est soumise à…", "choice", options=[("is", "L'impôt sur les sociétés (IS)"), ("ir", "L'impôt sur le revenu (IR)")],
       help_="SASU, SAS, SARL et EURL sont à l'IS par défaut ; EI et micro à l'IR.", kind="entreprise", section="Fiscalité",
       when=lambda p: p.get("forme") not in ("Micro-entreprise",)),
    _q("ca_estime", "Chiffre d'affaires annuel estimé ?", "number", "Détermine le régime de TVA et d'imposition (micro, simplifié, normal).", kind="entreprise", section="Fiscalité", unit="€"),
    _q("tva_regime", "Régime de TVA ?", "choice", options=[("franchise", "Franchise en base (pas de TVA)"), ("rsi", "Réel simplifié (CA12 annuelle)"),
       ("reel_mensuel", "Réel normal mensuel (CA3)"), ("reel_trimestriel", "Réel normal trimestriel (TVA < 4 000 €/an)"), ("ne_sais_pas", "Je ne sais pas")],
       help_="L'IA peut le déterminer à partir de votre chiffre d'affaires.", kind="entreprise", section="Fiscalité"),
    _q("tva_exigibilite", "Vendez-vous surtout des services ou des biens ?", "choice", options=[("encaissements", "Des services (TVA à l'encaissement)"), ("debits", "Des biens (TVA à la facturation)")],
       kind="entreprise", section="Fiscalité", when=lambda p: p.get("tva_regime") != "franchise"),
    _q("international", "Travaillez-vous avec des clients ou fournisseurs à l'étranger ?", "multi",
       options=[("ue_clients", "Clients dans l'UE"), ("hors_ue_clients", "Clients hors UE"), ("ue_fournisseurs", "Fournisseurs UE (SaaS, matériel…)"), ("non", "Non")], kind="entreprise", section="Fiscalité"),
    _q("dirigeant_remuneration", "Le dirigeant se verse-t-il une rémunération ?", "choice",
       options=[("salaire", "Oui, un salaire"), ("dividendes", "Non, uniquement des dividendes"), ("mixte", "Salaire et dividendes"), ("rien", "Rien pour l'instant")], kind="entreprise", section="Social"),
    _q("effectif", "Combien de salariés (hors dirigeant) ?", "number", kind="entreprise", section="Social"),
    _q("locaux", "Vos locaux professionnels ?", "choice", options=[("domicile", "Domiciliation au domicile"), ("location", "Location d'un bureau"), ("domiciliation", "Société de domiciliation"), ("propriete", "Propriétaire")],
       help_="Détermine la CFE et les charges déductibles.", kind="entreprise", section="Social"),
    _q("vehicule", "L'entreprise a-t-elle un véhicule ?", "choice", options=[("non", "Non"), ("societe", "Oui, au nom de la société"), ("perso", "Véhicule personnel utilisé (indemnités km)")], kind="entreprise", section="Social"),
]
BY_ID = {q["id"]: q for q in QUESTIONS}

def get(con, eid):
    r = con.execute("SELECT data, completed FROM profiles WHERE entity_id=?", (eid,)).fetchone()
    return (json.loads(r["data"]) if r else {}), bool(r and r["completed"])

def save(con, eid, data, completed=None):
    cur = get(con, eid)[1] if completed is None else completed
    con.execute("""INSERT INTO profiles(entity_id,data,completed,updated) VALUES(?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(entity_id) DO UPDATE SET data=excluded.data, completed=excluded.completed, updated=CURRENT_TIMESTAMP""",
                (eid, json.dumps(data, ensure_ascii=False), int(bool(cur))))

def applicable(kind, p):
    return [q for q in QUESTIONS if q["kind"] == kind and q["when"](p)]

def next_question(kind, p):
    for q in applicable(kind, p):
        if q["id"] not in p and q["id"] not in p.get("_skipped", []):
            return q
    return None

def progress(kind, p):
    qs = applicable(kind, p)
    done = sum(1 for q in qs if q["id"] in p or q["id"] in p.get("_skipped", []))
    return round(done / len(qs) * 100) if qs else 100

def public(q, p=None):
    if not q:
        return None
    return {k: q[k] for k in ("id", "text", "type", "help", "options", "section", "unit", "placeholder")}

# ---------------- Compréhension des réponses ----------------
NUM_WORDS = {"zero": 0, "aucun": 0, "aucune": 0, "pas": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8}

def _norm(s):
    s = str(s).lower().strip()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ç", "c"), ("ô", "o"), ("î", "i"), ("û", "u"), ("·", "")):
        s = s.replace(a, b)
    return s

def _number(text):
    t = _norm(text).replace(" ", " ")
    m = re.search(r"(-?\d[\d\s.]*(?:,\d+)?)\s*(k|k€|000)?", t)
    if m:
        raw = m.group(1).replace(" ", "")
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") >= 1 and len(raw.split(".")[-1]) == 3:
            raw = raw.replace(".", "")
        v = float(raw)
        if m.group(2) in ("k", "k€"):
            v *= 1000
        return int(v) if v == int(v) else v
    for w, n in NUM_WORDS.items():
        if re.search(rf"\b{w}\b", t):
            return n
    return None

def parse_answer(q, value):
    """Interprète une réponse pour une question donnée (choix, oui/non, nombre, texte)."""
    if value is None:
        return None
    t = q["type"]
    if t == "yesno":
        if isinstance(value, bool):
            return value
        n = _norm(value)
        if re.search(r"\b(oui|yes|ouais|bien sur|exact|tout a fait|absolument)\b", n):
            return True
        if re.search(r"\b(non|no|pas|jamais|aucun)\b", n):
            return False
        return None
    if t == "number":
        return value if isinstance(value, (int, float)) else _number(value)
    if t == "choice":
        opts = q["options"]
        if any(value == o[0] for o in opts):
            return value
        n = _norm(value)
        for o, lab in opts:
            if _norm(o) in n or _norm(lab).split(" (")[0] in n:
                return o
        syn = {"marie": ["mari", "epoux", "epouse"], "pacse": ["pacs"], "union_libre": ["concubin", "en couple"], "celibataire": ["seul", "celib"],
               "divorce": ["separe", "divorc"], "salarie": ["cdi", "cdd", "employe", "salari"], "independant": ["auto-entrepreneur", "auto entrepreneur", "freelance", "micro", "liberal"],
               "retraite": ["retrait"], "chomage": ["chomage", "sans emploi", "pole emploi", "france travail"], "proprietaire": ["proprio"], "locataire": ["loue", "location"]}
        for o, words in syn.items():
            if any(o == x[0] for x in opts) and any(w in n for w in words):
                return o
        return None
    if t == "multi":
        if isinstance(value, list):
            return value
        n = _norm(value)
        out = [o for o, lab in q["options"] if _norm(o) in n or _norm(lab).split(" (")[0] in n]
        return out or None
    if t == "date":
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(value)) or None
        if m:
            return m.group(0)
        m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", str(value))
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else (str(value).strip() or None)
    if q["id"] in ("prenom", "conjoint_prenom"):
        return _first_name(str(value))
    return str(value).strip() or None

def _first_name(text):
    m = re.search(r"(?:je m'appelle|je suis|moi c'est|c'est|il s'appelle|elle s'appelle|prenom\s*:?)\s+([A-ZÉÈÀÂÎÏÔÛÇ][\w\-éèêëàâîïôûç]+)", text, re.I)
    if m:
        return m.group(1).capitalize()
    w = re.findall(r"[A-Za-zÀ-ÿ\-]+", text)
    return w[0].capitalize() if len(w) <= 3 and w else None

def extract_free_text(kind, p, text):
    """Extraction multi-champs depuis une réponse libre (règles locales)."""
    n = _norm(text)
    out = {}
    if kind == "particulier":
        for o, words in (("marie", ["marie", "mariee", "epoux", "epouse", "mon mari", "ma femme"]), ("pacse", ["pacse", "pacs"]),
                         ("union_libre", ["concubin", "en couple"]), ("divorce", ["divorce", "separe"]), ("veuf", ["veuf", "veuve"]),
                         ("celibataire", ["celibataire", "seul"])):
            if any(re.search(rf"\b{w}", n) for w in words):
                out["situation"] = o; break
        m = re.search(r"(\d+|un|une|deux|trois|quatre|cinq|six|pas d'|aucun|zero)\s*(?:petits?\s*)?enfants?", n)
        if m:
            w = m.group(1).strip()
            out["enfants"] = int(w) if w.isdigit() else (0 if w.startswith("pas") else NUM_WORDS.get(w))
        years = [int(y) for y in re.findall(r"\b(19[3-9]\d|20[0-2]\d)\b", n)]
        kid_years = [y for y in years if y > Y - 26]
        if "enfant" in n and kid_years:
            out["enfants_naissances"] = ", ".join(str(y) for y in kid_years)
        if re.search(r"\bne\b|\bnee\b|naissance|j'ai \d+ ans", n):
            adult = [y for y in years if y <= Y - 18]
            if adult:
                out["naissance"] = adult[0]
            m2 = re.search(r"j'ai (\d{2}) ans", n)
            if m2:
                out["naissance"] = Y - int(m2.group(1))
        for o, words in (("salarie", ["salarie", "cdi", "cdd", "employe"]), ("independant", ["auto-entrepreneur", "auto entrepreneur", "freelance", "independant", "micro-entrepreneur"]),
                         ("dirigeant", ["dirigeant", "gerant", "president de", "ma societe"]), ("retraite", ["retraite"]), ("chomage", ["chomage", "sans emploi"]), ("etudiant", ["etudiant"])):
            if any(w in n for w in words):
                out.setdefault("activite", o)
        if "proprietaire" in n and "locatif" not in n:
            out["logement"] = "proprietaire"
        elif "locataire" in n:
            out["logement"] = "locataire"
        if re.search(r"(je loue|loyers?|appartement en location|investissement locatif|lmnp)", n) and "locataire" not in n:
            out["immobilier_locatif"] = True
        m = re.search(r"(\d[\d\s.]*)\s*(k|k€|€|euros)?\s*(?:net\s*)?(?:imposable\s*)?(?:par an|annuel|/an)", n)
        if m and out.get("activite") in ("salarie", "dirigeant"):
            out["salaire_annuel"] = _number(m.group(0))
        m = re.search(r"\b(\d{2}|2a|2b|97\d)\b(?=\s*$|\s*\)|,)", n)
        for city, dep in (("paris", "75"), ("lyon", "69"), ("marseille", "13"), ("bordeaux", "33"), ("lille", "59"), ("toulouse", "31"), ("nantes", "44"), ("nice", "06")):
            if city in n:
                out["departement"] = dep
    else:
        for f in ("SASU", "SAS", "SARL", "EURL", "SCI"):
            if re.search(rf"\b{f.lower()}\b", n):
                out["forme"] = f; break
        if "micro" in n or "auto-entrepreneur" in n:
            out["forme"] = "Micro-entreprise"
        m = re.search(r"(\d[\d\s.,]*)\s*(k|k€|€|euros)?\s*(de )?(ca|chiffre)", n) or re.search(r"(ca|chiffre d'affaires)[^\d]*(\d[\d\s.,]*\s*k?)", n)
        if m:
            out["ca_estime"] = _number(m.group(0))
        m = re.search(r"(\d+)\s*salaries?", n)
        if m:
            out["effectif"] = int(m.group(1))
        if out.get("ca_estime") is None and len(text) > 15 and "activite_desc" not in p:
            out["activite_desc"] = text.strip()[:200]
    return {k: v for k, v in out.items() if v is not None}

def ai_turn(kind, p, q, text):
    """Avec Claude : extrait tous les champs mentionnés et formule la prochaine question naturellement."""
    if not ai.enabled():
        return None
    fields = [{"id": x["id"], "question": x["text"], "type": x["type"], "options": [o for o, _ in x["options"]]} for x in QUESTIONS if x["kind"] == kind]
    sys = ("Tu es l'assistant fiscal d'un logiciel de comptabilité français. Tu mènes un entretien d'accueil chaleureux et efficace. "
           "À partir de la réponse de l'utilisateur, extrais TOUTES les informations correspondant aux champs listés (même celles qui "
           "répondent à des questions futures). Valeurs : nombres sans unité, booléens true/false, codes d'options exacts, dates AAAA-MM-JJ. "
           "Réponds UNIQUEMENT en JSON : {\"fields\": {id: valeur}, \"comment\": \"courte remarque utile ou empathique (1 phrase, optionnelle)\"}.")
    user = json.dumps({"champs": fields, "profil_actuel": {k: v for k, v in p.items() if not k.startswith("_")},
                       "question_posee": q["text"] if q else None, "reponse": text}, ensure_ascii=False)
    res = ai._json(ai.llm(sys, user, 1200))
    if not isinstance(res, dict):
        return None
    clean = {}
    for k, v in (res.get("fields") or {}).items():
        if k in BY_ID and BY_ID[k]["kind"] == kind:
            pv = parse_answer(BY_ID[k], v) if not isinstance(v, (bool, int, float, list)) else v
            if pv is not None:
                clean[k] = pv
    return {"fields": clean, "comment": res.get("comment")}

def answer(con, eid, kind, qid, value=None, free_text=None, skip=False):
    p, completed = get(con, eid)
    q = BY_ID.get(qid) if qid else None
    understood, comment = {}, None
    if skip and q:
        p.setdefault("_skipped", []).append(qid)
    else:
        text = free_text if free_text is not None else value
        if isinstance(text, str):
            r = ai_turn(kind, p, q, text)
            if r:
                understood, comment = r["fields"], r.get("comment")
        if q and qid not in understood:
            v = parse_answer(q, value if value is not None else free_text)
            if v is not None:
                understood[qid] = v
        if isinstance(text, str) and len(text) > 12:
            for k, v in extract_free_text(kind, p, text).items():
                understood.setdefault(k, v)
        if q and qid not in understood and not understood:
            return {"ok": False, "message": "Je n'ai pas bien compris. Pouvez-vous préciser ?" + (" (choisissez une option)" if q["type"] in ("choice", "multi", "yesno") else ""),
                    "question": public(q), "progress": progress(kind, p)}
        p.update(understood)
    nxt = next_question(kind, p)
    if not nxt:
        completed = True
    save(con, eid, p, completed)
    if completed:
        apply(con, eid, kind, p)
    def lab(k, v):
        q_ = BY_ID.get(k)
        if q_ and q_["type"] == "choice":
            return dict(q_["options"]).get(v, v)
        if q_ and q_["type"] == "yesno":
            return "oui" if v else "non"
        if q_ and q_["type"] == "multi":
            return ", ".join(dict(q_["options"]).get(x, x) for x in v)
        return v
    return {"ok": True, "compris": {BY_ID[k]["text"] if k in BY_ID else k: lab(k, v) for k, v in understood.items()}, "commentaire": comment,
            "question": public(nxt), "progress": progress(kind, p), "termine": nxt is None, "profil": summary(kind, p)}

def summary(kind, p):
    out = []
    for q in applicable(kind, p):
        if q["id"] in p:
            v = p[q["id"]]
            if q["type"] == "choice":
                v = dict(q["options"]).get(v, v)
            elif q["type"] == "multi":
                v = ", ".join(dict(q["options"]).get(x, x) for x in (v or []))
            elif q["type"] == "yesno":
                v = "Oui" if v else "Non"
            out.append({"section": q["section"], "id": q["id"], "question": q["text"], "reponse": v})
    return out

def apply(con, eid, kind, p):
    """Applique le profil au paramétrage du dossier."""
    if kind != "entreprise":
        return
    upd = {}
    if p.get("forme"):
        upd["legal_form"] = p["forme"]
    reg = p.get("tva_regime")
    if reg == "ne_sais_pas" or (not reg and p.get("ca_estime")):
        reg = recommend_tva(p)
        p["tva_regime"] = reg
    if reg:
        upd["tva_regime"] = "franchise" if reg == "franchise" else "reel"
        db.set_setting(con, eid, "tva_periodicite", reg)
    if p.get("tva_exigibilite"):
        upd["tva_exigibilite"] = p["tva_exigibilite"]
    for k, v in upd.items():
        con.execute(f"UPDATE entities SET {k}=? WHERE id=?", (v, eid))
    if p.get("effectif") is not None:
        db.set_setting(con, eid, "effectif", p["effectif"])

def recommend_tva(p):
    ca = float(p.get("ca_estime") or 0)
    services = p.get("tva_exigibilite", "encaissements") == "encaissements"
    seuil_franchise = 37500 if services else 85000
    seuil_rsi = 254000 if services else 840000
    if ca <= seuil_franchise:
        return "franchise"
    if ca <= seuil_rsi:
        return "rsi"
    return "reel_mensuel"

# ---------------- Obligations et calendrier ----------------
def deadlines(kind, p, year=None):
    """Calendrier fiscal personnalisé (dates indicatives : vérifier le calendrier officiel publié chaque année)."""
    y = year or Y
    out = []
    if kind == "particulier":
        dep = str(p.get("departement") or "")
        num = int(dep) if dep.isdigit() else (20 if dep.lower() in ("2a", "2b") else 99)
        limite = f"{y}-05-21" if num <= 19 else f"{y}-05-28" if num <= 54 else f"{y}-06-04"
        out += [{"date": f"{y}-04-10", "titre": "Ouverture de la déclaration de revenus en ligne", "type": "info"},
                {"date": limite, "titre": f"Date limite de déclaration en ligne (département {dep or '?'})", "type": "echeance"},
                {"date": f"{y}-07-25", "titre": "Avis d'impôt disponible", "type": "info"},
                {"date": f"{y}-09-15", "titre": "Paiement du solde d'impôt (si > 300 € : prélevé en 4 fois de septembre à décembre)", "type": "paiement"}]
        if p.get("logement") == "proprietaire" or p.get("immobilier_locatif"):
            out.append({"date": f"{y}-10-15", "titre": "Taxe foncière", "type": "paiement"})
        if "crypto" in (p.get("placements") or []) or "etranger" in (p.get("placements") or []):
            out.append({"date": limite, "titre": "Formulaires 3916 (comptes à l'étranger) et 2086 (cryptoactifs) avec la déclaration", "type": "echeance"})
    else:
        reg = p.get("tva_regime")
        if reg == "reel_mensuel":
            out += [{"date": f"{y}-{m:02d}-19", "titre": f"Déclaration CA3 et paiement de la TVA de {['', 'décembre', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre'][m]}", "type": "echeance"} for m in range(1, 13)]
        elif reg == "reel_trimestriel":
            out += [{"date": f"{y}-{m:02d}-19", "titre": "Déclaration CA3 trimestrielle", "type": "echeance"} for m in (1, 4, 7, 10)]
        elif reg == "rsi":
            out += [{"date": f"{y}-05-05", "titre": "Déclaration annuelle de TVA CA12", "type": "echeance"},
                    {"date": f"{y}-07-15", "titre": "Acompte de TVA (55 %)", "type": "paiement"}, {"date": f"{y}-12-15", "titre": "Acompte de TVA (40 %)", "type": "paiement"}]
        if p.get("regime_fiscal", "is" if p.get("forme") in ("SASU", "SAS", "SARL", "EURL") else "ir") == "is":
            out += [{"date": f"{y}-{m}", "titre": "Acompte d'impôt sur les sociétés", "type": "paiement"} for m in ("03-15", "06-15", "09-15", "12-15")]
            out += [{"date": f"{y}-05-05", "titre": "Liasse fiscale 2065 + 2033 (exercice clos au 31/12) et relevé de solde IS", "type": "echeance"}]
        else:
            out.append({"date": f"{y}-05-05", "titre": "Déclaration de résultat (2031 / 2035) et report sur la 2042-C-PRO", "type": "echeance"})
        out.append({"date": f"{y}-12-15", "titre": "Cotisation foncière des entreprises (CFE)", "type": "paiement"})
        if (p.get("effectif") or 0) > 0 or p.get("dirigeant_remuneration") in ("salaire", "mixte"):
            out += [{"date": f"{y}-{m:02d}-{'05' if (p.get('effectif') or 0) >= 50 else '15'}", "titre": "DSN mensuelle", "type": "echeance"} for m in range(1, 13)]
        out.append({"date": f"{y}-06-30", "titre": "Approbation des comptes (AG) et dépôt au greffe dans le mois suivant", "type": "echeance"})
    today = dt.date.today().isoformat()
    return sorted([{**d, "passe": d["date"] < today} for d in out], key=lambda d: d["date"])
