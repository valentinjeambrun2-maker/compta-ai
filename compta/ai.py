"""Couche IA : catégorisation des opérations, extraction de factures, assistant comptable/fiscal.

Fonctionne en deux modes :
 - avec ANTHROPIC_API_KEY : appelle Claude (modèle configurable via COMPTA_MODEL) ;
 - sans clé : moteur de règles local (aucune donnée ne sort de la machine).
"""
import json, os, re, urllib.request

MODEL = os.environ.get("COMPTA_MODEL", "claude-opus-5-5")

def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))

def llm(system, user, max_tokens=2000):
    """user : texte, ou liste de blocs de contenu (texte, image, document PDF)."""
    if not enabled():
        return None
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    except Exception as e:  # l'IA ne doit jamais bloquer la compta
        print("[IA] appel échoué :", e)
        return None

def _json(text):
    if not text:
        return None
    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except Exception:
        return None

# ---------- Règles locales : (regex, compte, tva, confiance) ----------
R_ENT_OUT = [
 (r"urssaf|ssi\b|cipav|carmf|retraite", "646", 0, .9), (r"dgfip|impots?|cfe\b|cvae", "635", 0, .85),
 (r"\btva\b", "44551", 0, .8), (r"salaire|paie|virement salari", "641", 0, .8),
 (r"loyer|bail|regus|coworking|wework", "613", 20, .85), (r"axa|maif|macif|allianz|hiscox|assurance|generali", "616", 0, .9),
 (r"edf|engie|total ?energies|electricit|gaz\b|eau\b|veolia", "606", 20, .85),
 (r"restaurant|brasserie|resto|deliveroo|uber ?eats|dejeuner|cafe\b", "6257", 10, .75),
 (r"sncf|ouigo|air ?france|easyjet|transavia|uber|bolt|taxi|g7|heetch|blablacar|ratp", "625", 0, .85),   # transport de personnes : TVA non déductible
 (r"hotel|ibis|novotel|accor|airbnb|booking", "625", 0, .75),                                       # hébergement salariés/dirigeants : TVA non déductible
 (r"total\b|esso|shell|bp\b|carburant|station|avia|intermarche carbu", "625", 20, .7),             # carburant (VP : 80 % récupérable sur gazole/essence)
 (r"peage|vinci autoroute|sanef|aprr|parking|indigo", "625", 20, .75),
 (r"orange|sfr|bouygues|free ?mobile|free\b|sosh|ovh|o2switch|ionos|la poste|colissimo", "626", 20, .85),
 (r"frais|commission|agios|cotisation carte|abonnement banc|tenue de compte", "627", 0, .85),
 (r"google ?ads|facebook|meta|linkedin ads|tiktok ads|publicit", "623", 20, .85),
 (r"comptab|avocat|notaire|honoraire|expert", "622", 20, .8),
 (r"aws|amazon web|google cloud|gcp|azure|github|notion|slack|adobe|microsoft|figma|openai|anthropic|saas|abonnement", "628", 20, .75),
 (r"apple|ldlc|boulanger|darty|materiel|ordinateur|macbook", "2183", 20, .6),
 (r"amazon|fnac|bureau vallee|office depot|fourniture|ikea", "606", 20, .65),
 (r"interet|echeance pret|remboursement pret", "661", 0, .6),
]
R_ENT_IN = [(r"stripe|paypal|sumup|vir(ement)? .*(client|facture)|fact|vir sepa|virement", "706", 20, .6),
            (r"interet|livret", "761", 0, .8), (r"apport|capital", "101", 0, .7)]
R_PAR_OUT = [
 (r"loyer|bail|credit immo|syndic|foncia|nexity|charges copro", "600", 0, .85), (r"edf|engie|veolia|eau\b|gaz\b", "600", 0, .8),
 (r"carrefour|leclerc|auchan|lidl|aldi|intermarche|monoprix|franprix|casino|picard|boulang|super ?u|biocoop", "610", 0, .9),
 (r"sncf|ratp|navigo|uber|bolt|total\b|esso|shell|peage|parking|carburant", "620", 0, .85),
 (r"pharmacie|medecin|docteur|dentiste|mutuelle|hopital|clinique|ameli", "630", 0, .85),
 (r"netflix|spotify|disney|canal|cinema|fnac|deezer|steam|playstation|voyage|airbnb|booking", "640", 0, .8),
 (r"dgfip|impot|taxe fonciere|taxe habitation|amende", "650", 0, .9),
 (r"croix.rouge|restos du coeur|secours|unicef|msf|fondation|association|don\b|dons\b|emmaus|telethon", "660", 0, .8),
 (r"creche|assistante maternelle|garderie|pajemploi", "670", 0, .85), (r"cesu|aide a domicile|menage|o2\b|shiva|acadomia|soutien scolaire", "680", 0, .8),
 (r"ecole|universite|scolarit|cantine|formation", "690", 0, .75), (r"axa|maif|macif|allianz|assurance|matmut|groupama", "695", 0, .85),
]
R_PAR_IN = [(r"salaire|paie|traitement|remuneration", "700", 0, .9), (r"cnav|carsat|agirc|arrco|retraite|pension", "701", 0, .85),
            (r"loyer|locataire", "710", 0, .75), (r"dividende|coupon|interet|livret", "720", 0, .8), (r"caf\b|allocation", "790", 0, .7)]

def _strip(s):
    s = s.lower()
    for a, b in (("é","e"),("è","e"),("ê","e"),("à","a"),("ç","c"),("ô","o"),("î","i"),("û","u")):
        s = s.replace(a, b)
    return s

def categorize_rule(kind, label, amount):
    rules = (R_ENT_OUT if amount < 0 else R_ENT_IN) if kind == "entreprise" else (R_PAR_OUT if amount < 0 else R_PAR_IN)
    l = _strip(label)
    for rx, acc, tva, conf in rules:
        if re.search(rx, l):
            if acc == "2183" and abs(amount) < 50000:  # < 500 € HT : charge, pas immobilisation
                acc = "606"
            return {"account": acc, "tva_rate": tva, "confidence": conf, "reason": f"Règle : « {rx.split('|')[0]} »"}
    if kind == "entreprise" and amount > 0:
        return {"account": "706", "tva_rate": 20, "confidence": .4, "reason": "Encaissement non identifié → ventes par défaut"}
    return {"account": "471", "tva_rate": 0, "confidence": .1, "reason": "Non reconnu : compte d'attente"}

def categorize_batch(kind, rows, chart):
    res = [categorize_rule(kind, r["label"], r["amount"]) for r in rows]
    todo = [i for i, c in enumerate(res) if c["confidence"] < .8]
    if not todo or not enabled():
        return res
    for k in range(0, len(todo), 40):
        chunk = todo[k:k + 40]
        plan = "\n".join(f"{c}: {l}" for c, l in chart.items())
        ops = "\n".join(f'{j}|{rows[i]["date"]}|{rows[i]["label"]}|{rows[i]["amount"]/100:.2f}' for j, i in enumerate(chunk))
        sys = ("Tu es expert-comptable français. Pour chaque opération bancaire, choisis le compte le plus adapté du plan fourni "
               "et le taux de TVA récupérable (0, 5.5, 10 ou 20 ; 0 pour un particulier). Réponds UNIQUEMENT par un tableau JSON "
               '[{"i":index,"account":"code","tva_rate":n,"confidence":0-1,"reason":"courte justification"}].')
        out = _json(llm(sys, f"Type de dossier : {kind}\nPlan comptable :\n{plan}\n\nOpérations (index|date|libellé|montant €) :\n{ops}"))
        for o in out or []:
            try:
                i = chunk[int(o["i"])]
                if str(o["account"]) in chart:
                    res[i] = {"account": str(o["account"]), "tva_rate": float(o.get("tva_rate", 0)),
                              "confidence": min(float(o.get("confidence", .7)), .95), "reason": "IA : " + str(o.get("reason", ""))[:200]}
            except (KeyError, ValueError, IndexError, TypeError):
                continue
    return res

def extract_invoice(text):
    """Extrait les champs d'une facture (texte copié/OCR)."""
    sys = ("Extrais les données de cette facture française. Réponds UNIQUEMENT en JSON : "
           '{"party":"","number":"","date":"AAAA-MM-JJ","due":"AAAA-MM-JJ|null","lines":[{"label":"","qty":1,"unit_price":0.0,"tva_rate":20}]}'
           " (unit_price HT en euros).")
    data = _json(llm(sys, text[:15000]))
    if isinstance(data, dict) and data.get("lines"):
        data["source"] = "ia"
        return data
    # Repli : regex
    t = text.replace(" ", " ")
    num = re.search(r"(?:facture|invoice)\s*(?:n[°o]|#|:)?\s*([A-Z0-9\-_/]{3,})", t, re.I)
    d = re.search(r"(\d{2})[/.-](\d{2})[/.-](\d{4})", t)
    ht = re.search(r"total\s*h\.?t\.?\s*:?\s*([\d\s.,]+)", t, re.I)
    ttc = re.search(r"total\s*t\.?t\.?c\.?\s*:?\s*([\d\s.,]+)", t, re.I)
    rate = re.search(r"tva\s*(?:à|a|de)?\s*(\d{1,2}(?:[.,]\d)?)\s*%", t, re.I)
    r = float(rate.group(1).replace(",", ".")) if rate else 20.0
    from .ledger import cents
    if ht:
        pu = cents(ht.group(1).strip()) / 100
    elif ttc:
        pu = round(cents(ttc.group(1).strip()) / 100 / (1 + r / 100), 2)
    else:
        pu = 0.0
    first = next((l.strip() for l in t.splitlines() if l.strip()), "Fournisseur")
    return {"party": first[:60], "number": num.group(1) if num else "", "date": f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else "",
            "due": None, "lines": [{"label": "Selon facture", "qty": 1, "unit_price": pu, "tva_rate": r}], "source": "regles"}

def assistant(question, context):
    sys = ("Tu es l'assistant comptable et fiscal intégré au logiciel. Tu réponds en français, de façon précise et chiffrée, "
           "à partir des données du dossier fournies en JSON (montants en euros). Cite les articles/règles fiscales françaises pertinentes "
           "quand c'est utile, signale les points à vérifier et ne fabrique jamais de chiffres absents des données.")
    ans = llm(sys, f"Données du dossier :\n{json.dumps(context, ensure_ascii=False, default=str)}\n\nQuestion : {question}", 1500)
    if ans:
        return {"answer": ans, "mode": "ia"}
    q = _strip(question)
    m = lambda v: f"{float(v or 0):,.2f}".replace(",", "\u202f").replace(".", ",") + " €"
    c = context
    if "tva" in q:
        t = c.get("tva", {})
        a = f"TVA collectée : {m(t.get('collectee'))}, déductible : {m(t.get('deductible'))}. Solde à payer : {m(t.get('a_payer'))}" + (f" (crédit : {m(t.get('credit'))})" if t.get('credit') else "") + "."
    elif any(w in q for w in ("resultat", "benefice", "perte", "rentab")):
        a = f"Résultat de l'exercice : {m(c.get('resultat'))} (produits {m(c.get('produits'))}, charges {m(c.get('charges'))})."
    elif any(w in q for w in ("tresor", "banque", "solde", "argent")):
        a = f"Trésorerie (comptes 512 + 530) : {m(c.get('tresorerie'))}."
    elif any(w in q for w in ("impot", "is\b", "ir\b", "payer")):
        a = f"Estimation d'impôt : {c.get('impot_estime')}."
    else:
        a = ("Mode hors-ligne (pas de clé ANTHROPIC_API_KEY) : je sais répondre sur la TVA, le résultat, la trésorerie et l'impôt estimé. "
             "Configurez une clé API pour un assistant conversationnel complet.")
    return {"answer": a, "mode": "regles"}
