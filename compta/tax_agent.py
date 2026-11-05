"""Agent Impôts : prépare la déclaration de revenus complète d'un foyer, de bout en bout.

Sources, de la moins à la plus fiable (la plus fiable l'emporte, chaque montant garde sa provenance) :
  1. profil d'accueil (estimations données par l'utilisateur) ;
  2. comptabilité du foyer (opérations bancaires catégorisées) ;
  3. justificatifs importés et lus par l'IA (bulletin de décembre, IFU, attestations…).
L'agent calcule les parts, choisit les options les plus favorables (frais réels, régime foncier, barème ou PFU,
imposition commune ou séparée l'année du mariage), liste les pièces manquantes, contrôle la cohérence, puis :
  - dépose la déclaration en EDI-IR si un tiers déclarant habilité (expert-comptable, avocat, OGA) est configuré ;
  - sinon guide la saisie sur impots.gouv.fr écran par écran (la DGFiP n'offre pas d'API aux particuliers).
"""
import json, re, datetime as dt
from . import ai, ledger, tax, profile as P, foncier, documents, db, expenses

# ---------------- Justificatifs ----------------
DOC_TYPES = {
    "bulletin_decembre": ("Bulletin de salaire de décembre", ["bulletin", "net imposable", "cumul", "salaire brut"], {"net_imposable_annuel": "number"}),
    "attestation_pension": ("Attestation fiscale de pensions de retraite", ["retraite", "pension", "carsat", "agirc", "arrco", "cnav"], {"montant_imposable": "number"}),
    "attestation_chomage": ("Attestation France Travail", ["france travail", "pole emploi", "allocation", "are "], {"montant_imposable": "number"}),
    "ifu": ("Imprimé fiscal unique (IFU)", ["ifu", "imprime fiscal unique", "2dc", "2tr", "revenus de capitaux mobiliers"], {"dividendes_2dc": "number", "interets_2tr": "number", "credit_2ck": "number"}),
    "attestation_emploi_domicile": ("Attestation fiscale emploi à domicile (CESU, Pajemploi, organisme)", ["cesu", "attestation fiscale", "services a la personne", "emploi a domicile"], {"montant": "number"}),
    "attestation_garde": ("Attestation de frais de garde (crèche, assistante maternelle)", ["creche", "assistante maternelle", "pajemploi", "garde"], {"montant": "number"}),
    "recu_don": ("Reçu fiscal de don", ["recu fiscal", "cerfa 11580", "don", "article 200"], {"montant": "number", "aide_personnes": "bool"}),
    "avis_impot": ("Avis d'impôt de l'année précédente", ["avis d'impot", "revenu fiscal de reference", "plafond epargne retraite"],
                   {"revenu_fiscal_reference": "number", "taux_pas": "number", "plafond_per": "number", "deficits_fonciers": "number"}),
    "releve_charges_locatif": ("Relevé de charges / loyers d'un bien loué", ["loyer", "charges", "syndic", "gestion locative", "taxe fonciere"],
                               {"loyers": "number", "charges": "number", "taxe_fonciere": "number", "interets": "number"}),
    "tableau_amortissement": ("Tableau d'amortissement du prêt", ["tableau d'amortissement", "interets", "echeance", "capital restant"], {"interets_annuels": "number"}),
    "autre": ("Autre justificatif", [], {}),
}

def classify(text, filename=""):
    t = P._norm(text + " " + filename)
    best, score = "autre", 0
    for k, (_, kws, _) in DOC_TYPES.items():
        s = sum(1 for w in kws if w in t)
        if s > score:
            best, score = k, s
    return best

def _amount_after(text, labels):
    t = P._norm(text)
    for lab in labels:
        m = re.search(lab + r"[^\d\-]{0,40}(-?\d[\d\s .]*,\d{2}|-?\d[\d\s .]*)", t)
        if m:
            return ledger.cents(m.group(1).replace(" ", " ").strip()) / 100
    return None

RULES = {
    "bulletin_decembre": {"net_imposable_annuel": [r"net imposable cumul", r"cumul net imposable", r"net fiscal cumul", r"net imposable annuel"]},
    "attestation_pension": {"montant_imposable": [r"montant imposable", r"montant a declarer", r"total imposable"]},
    "attestation_chomage": {"montant_imposable": [r"montant imposable", r"montant a declarer"]},
    "ifu": {"dividendes_2dc": [r"2dc"], "interets_2tr": [r"2tr"], "credit_2ck": [r"2ck"]},
    "attestation_emploi_domicile": {"montant": [r"montant (?:total )?(?:a declarer|des sommes|paye|verse)", r"total"]},
    "attestation_garde": {"montant": [r"montant (?:total )?(?:a declarer|paye|verse)", r"total"]},
    "recu_don": {"montant": [r"montant du don", r"somme de", r"montant"]},
    "avis_impot": {"revenu_fiscal_reference": [r"revenu fiscal de reference"], "taux_pas": [r"taux de prelevement"], "plafond_per": [r"plafond"]},
    "releve_charges_locatif": {"loyers": [r"loyers"], "charges": [r"charges"], "taxe_fonciere": [r"taxe fonciere"]},
    "tableau_amortissement": {"interets_annuels": [r"total des interets", r"interets"]},
}

def read_tax_document(data, mime, filename=""):
    """Lit un justificatif fiscal : type détecté et montants clés extraits."""
    if ai.enabled():
        import base64
        b64 = base64.b64encode(data).decode()
        mime_ = documents._sniff(data, mime)
        block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}} if mime_ == "application/pdf"
                 else {"type": "image", "source": {"type": "base64", "media_type": mime_, "data": b64}})
        schema = {k: {"libelle": v[0], "champs": v[2]} for k, v in DOC_TYPES.items()}
        prompt = ("Identifie ce justificatif fiscal français parmi les types suivants et extrais ses montants ANNUELS (en euros, nombres). "
                  f"Types : {json.dumps(schema, ensure_ascii=False)}. Réponds UNIQUEMENT en JSON : "
                  '{"type": "code", "annee": 2025, "champs": {...}, "beneficiaire": "déclarant 1|déclarant 2|enfant|inconnu", "remarque": ""}')
        res = ai._json(ai.llm("Tu es un fiscaliste français qui lit des justificatifs.", [block, {"type": "text", "text": prompt}], 1200))
        if isinstance(res, dict) and res.get("type") in DOC_TYPES:
            res["source"] = "ia-vision"
            return res
    mime_ = documents._sniff(data, mime)
    text = documents.pdf_text(data) if mime_ == "application/pdf" else documents.ocr_image(data)
    if not text.strip():
        raise documents.DocumentError("Aucun texte lisible : configurez ANTHROPIC_API_KEY pour la lecture des documents scannés et des photos.")
    kind = classify(text, filename)
    champs = {}
    for k, pats in RULES.get(kind, {}).items():
        v = _amount_after(text, pats)
        if v is not None:
            champs[k] = v
    if kind == "recu_don":
        champs["aide_personnes"] = bool(re.search(r"aide aux personnes en difficulte|restos du coeur|secours|fourniture de repas|soins", P._norm(text)))
    years = re.findall(r"\b(20[2-3]\d)\b", text)
    return {"type": kind, "annee": int(max(years)) if years else None, "champs": champs, "source": "texte+regles", "texte": text[:3000]}

def add_document(con, eid, year, name, mime, data, kind=None, beneficiaire=None):
    r = read_tax_document(data, mime, name)
    if kind:
        r["type"] = kind
    if beneficiaire:
        r["beneficiaire"] = beneficiaire
    did = con.execute("INSERT INTO tax_documents(entity_id,year,kind,name,mime,data,extracted) VALUES(?,?,?,?,?,?,?)",
                      (eid, year, r["type"], name, mime, data, json.dumps(r, ensure_ascii=False))).lastrowid
    return {"id": did, **{k: v for k, v in r.items() if k != "texte"}, "libelle": DOC_TYPES[r["type"]][0]}

def list_documents(con, eid, year):
    out = []
    for d in con.execute("SELECT id, kind, name, extracted, created FROM tax_documents WHERE entity_id=? AND year=? ORDER BY id", (eid, year)):
        x = json.loads(d["extracted"] or "{}")
        out.append({"id": d["id"], "type": d["kind"], "libelle": DOC_TYPES.get(d["kind"], ("?",))[0], "nom": d["name"], "champs": x.get("champs", {}),
                    "beneficiaire": x.get("beneficiaire"), "cree": d["created"]})
    return out

# ---------------- Construction de la déclaration ----------------
def _years(s):
    return [int(y) for y in re.findall(r"\d{4}", str(s or ""))]

def compute_parts(p, year):
    couple = p.get("situation") in ("marie", "pacse")
    base = 2.0 if couple else 1.0
    n = int(p.get("enfants") or 0) + int(p.get("enfants_majeurs") or 0)
    alt = bool(p.get("garde_alternee"))
    enf = 0.0
    for i in range(n):
        full = 0.5 if i < 2 else 1.0
        enf += full / 2 if alt and i < int(p.get("enfants") or 0) else full
    extra = 0.0
    detail = [f"{'Couple' if couple else 'Personne seule'} : {base:g} part(s)"]
    if n:
        detail.append(f"{n} enfant(s) à charge{' (résidence alternée)' if alt else ''} : +{enf:g}")
    if p.get("parent_isole") and n and not couple:
        extra += 0.5; detail.append("Parent isolé (case T) : +0,5")
    if p.get("invalidite"):
        extra += 0.5; detail.append("Invalidité (case P/F) : +0,5")
    return base + enf + extra, detail

def _frais_reels_km(p, sal, year):
    km = float(p.get("trajet_km") or 0)
    cv = int(p.get("trajet_cv") or 0)
    if not km or not cv or not sal:
        return None
    jours = max(0, 218 - 47 * int(p.get("teletravail_jours") or 0))
    km_an = min(km, 40) * 2 * jours   # au-delà de 40 km aller, justification de l'éloignement requise
    montant = expenses.km_allowance(km_an, cv, km_an)
    if km_an > 5000:  # tranche 5 001 - 20 000 km : a × d + b
        cvb = max(3, min(7, cv))
        _, a, b = expenses.BAREME_KM[cvb][1]
        montant = round(km_an * a + b, 2)
    repas = 0
    return {"km_annuels": round(km_an), "jours": jours, "frais_kilometriques": montant, "repas": repas, "total": round(montant + repas)}

def gather(con, eid, year):
    """Rassemble toutes les données disponibles avec leur provenance."""
    p, _ = P.get(con, eid)
    val, src = {}, {}
    def put(k, v, s):
        if v not in (None, "", 0):
            val[k], src[k] = v, s
    # 1. Profil
    for k, pk in (("salaires", "salaire_annuel"), ("salaires_d2", "conjoint_salaire"), ("pensions", "pension_retraite"), ("chomage", "chomage_montant"),
                  ("dividendes", "dividendes"), ("per_versements", "per_versements"), ("dons", "dons_annuels"), ("dons_aide", "dons_aide"),
                  ("emploi_domicile", "emploi_domicile"), ("garde_enfants", "garde_montant"), ("pension_alimentaire", "pension_versee"), ("ehpad", "ehpad")):
        put(k, p.get(pk), "profil")
    if val.get("dons") and val.get("dons_aide"):
        val["dons"] = max(0, val["dons"] - val["dons_aide"])
    if p.get("micro_type", "").startswith("micro") and p.get("micro_ca"):
        put(p["micro_type"], p["micro_ca"], "profil")
    # 2. Comptabilité du foyer (opérations catégorisées de l'année)
    s, e = f"{year}-01-01", f"{year}-12-31"
    b = {x["account"]: x["solde"] for x in ledger.balances(con, eid, s, e)} if ledger.entity(con, eid)["kind"] == "particulier" else {}
    rev = lambda c: max(0, -b.get(c, 0)) / 100
    dep = lambda c: max(0, b.get(c, 0)) / 100
    for k, acc, kind in (("dons", "660", dep), ("dons_aide", "661", dep), ("emploi_domicile", "680", dep), ("garde_enfants", "670", dep),
                         ("pension_alimentaire", "691", dep), ("per_versements", "692", dep), ("chomage", "702", rev), ("pensions", "701", rev)):
        v = kind(acc)
        if v and (k not in val or (src.get(k) == "profil" and v >= float(val[k]))):
            put(k, v, "comptabilite")   # une comptabilité partielle ne doit pas réduire l'estimation annuelle
    salaires_banque = rev("700")
    # 3. Justificatifs (prioritaires)
    for d in list_documents(con, eid, year):
        c, t, ben = d["champs"], d["type"], (d.get("beneficiaire") or "")
        d2 = "2" in ben
        if t == "bulletin_decembre" and c.get("net_imposable_annuel"):
            put("salaires_d2" if d2 else "salaires", c["net_imposable_annuel"], f"document : {d['nom']}")
        elif t == "attestation_pension" and c.get("montant_imposable"):
            put("pensions_d2" if d2 else "pensions", c["montant_imposable"], f"document : {d['nom']}")
        elif t == "attestation_chomage" and c.get("montant_imposable"):
            put("chomage_d2" if d2 else "chomage", c["montant_imposable"], f"document : {d['nom']}")
        elif t == "ifu":
            put("dividendes", c.get("dividendes_2dc"), f"document : {d['nom']}"); put("interets", c.get("interets_2tr"), f"document : {d['nom']}")
        elif t == "attestation_emploi_domicile":
            put("emploi_domicile", c.get("montant"), f"document : {d['nom']}")
        elif t == "attestation_garde":
            put("garde_enfants", c.get("montant"), f"document : {d['nom']}")
        elif t == "recu_don" and c.get("montant"):
            k = "dons_aide" if c.get("aide_personnes") else "dons"
            prev = val.get(k, 0) if src.get(k, "").startswith("document") else 0
            put(k, prev + c["montant"], "documents : reçus fiscaux")
        elif t == "avis_impot":
            for k in ("taux_pas", "plafond_per", "deficits_fonciers", "revenu_fiscal_reference"):
                if c.get(k):
                    val["avis_" + k], src["avis_" + k] = c[k], f"document : {d['nom']}"
    return p, val, src, salaires_banque

def build(con, eid, year, overrides=None):
    p, val, src, sal_banque = gather(con, eid, year)
    for k, v in (overrides or {}).items():
        val[k], src[k] = v, "saisie manuelle"
    parts, parts_detail = compute_parts(p, year)
    kids = [y for y in _years(p.get("enfants_naissances")) if year - y < 6]
    d = {k: v for k, v in val.items() if k in tax.CASES or k in ("frais_reels", "frais_reels_d2")}
    d.update({"situation": p.get("situation", "celibataire"), "enfants": int(p.get("enfants") or 0), "parts": parts,
              "enfants_moins_6": len(kids) or (1 if d.get("garde_enfants") else 0), "micro_vl": bool(p.get("versement_liberatoire"))})
    sco = {"college": 0, "lycee": 0, "superieur": 0}
    for y in _years(p.get("enfants_naissances")):
        age = year - y
        if 11 <= age <= 14: sco["college"] += 1
        elif 15 <= age <= 17: sco["lycee"] += 1
    d["scolarite"] = sco
    # Foncier
    fon = None
    if p.get("immobilier_locatif") and p.get("location_type") in ("nue", "les_deux"):
        biens = [{"nom": "Biens loués (profil)", "loyers": p.get("loyers_annuels") or 0, "interets": p.get("interets_annuels") or 0,
                  "frais_administration": p.get("charges_foncieres") or 0}]   # charges globales indiquées lors de l'entretien
        fon = choose_foncier(d, biens, val.get("avis_deficits_fonciers"), year)
        d.update(fon["entrees"])
    optim = []
    # Frais réels vs forfait 10 %
    fr = _frais_reels_km(p, val.get("salaires"), year)
    if fr:
        base = tax.impot_revenu(d, year)
        alt = tax.impot_revenu({**d, "frais_reels": fr["total"]}, year)
        gain = base["total_a_payer"] - alt["total_a_payer"]
        if gain > 0:
            d["frais_reels"] = fr["total"]
            optim.append({"titre": "Frais réels plutôt que l'abattement de 10 %", "gain": gain, "applique": True,
                          "detail": f"{fr['km_annuels']} km/an × barème {p.get('trajet_cv')} CV = {fr['frais_kilometriques']} € (> abattement forfaitaire). Conservez un justificatif de distance et de jours travaillés."})
        else:
            optim.append({"titre": "Abattement forfaitaire de 10 % conservé", "gain": 0, "applique": True,
                          "detail": f"Vos frais réels estimés ({fr['total']} €) sont inférieurs à l'abattement de 10 %."})
    # PFU vs barème
    if val.get("dividendes") or val.get("interets"):
        a = tax.impot_revenu(d, year); b = tax.impot_revenu({**d, "option_bareme": True}, year)
        if b["total_a_payer"] < a["total_a_payer"]:
            d["option_bareme"] = True
            optim.append({"titre": "Option pour le barème progressif (case 2OP)", "gain": a["total_a_payer"] - b["total_a_payer"], "applique": True,
                          "detail": "Avec votre tranche d'imposition, l'abattement de 40 % sur les dividendes rend le barème plus avantageux que le PFU de 12,8 %. L'option s'applique à tous vos revenus de capitaux."})
        else:
            optim.append({"titre": "Prélèvement forfaitaire unique (PFU) conservé", "gain": 0, "applique": True, "detail": "Le PFU de 12,8 % est plus favorable que le barème pour vous."})
    if fon:
        optim.append(fon["optimisation"])
    calc = tax.impot_revenu({**d, "pas_verse": 0}, year)
    # Imposition commune / séparée (année du mariage ou du PACS)
    if p.get("situation_changement") and p.get("situation") in ("marie", "pacse"):
        s1 = tax.impot_revenu({"salaires": d.get("salaires"), "parts": 1 + (parts - 2) / 2 if parts > 2 else 1}, year)["total_a_payer"]
        s2 = tax.impot_revenu({"salaires": d.get("salaires_d2"), "parts": 1 + (parts - 2) / 2 if parts > 2 else 1}, year)["total_a_payer"]
        sep, com = s1 + s2, calc["total_a_payer"]
        optim.append({"titre": "Année du mariage / PACS : imposition " + ("commune" if com <= sep else "séparée"), "gain": abs(sep - com), "applique": com <= sep,
                      "detail": f"Commune : {com} € · séparée (estimation) : {sep} €. " + ("Déclaration commune retenue." if com <= sep else "Cochez l'option d'imposition séparée lors de la déclaration.")})
    # PER (conseil)
    tmi = calc["tmi_num"]
    if tmi >= .30:
        plaf = val.get("avis_plafond_per")
        optim.append({"titre": "Conseil : verser sur un PER avant le 31 décembre", "gain": round(1000 * tmi), "applique": False,
                      "detail": f"À votre tranche ({calc['tmi']}), 1 000 € versés réduisent l'impôt d'environ {round(1000 * tmi)} €" + (f" (plafond disponible : {plaf:,.0f} €)".replace(",", " ") if plaf else " (plafond indiqué sur votre avis d'impôt).")})
    if p.get("enfants_majeurs"):
        optim.append({"titre": "Enfant majeur : rattachement ou pension alimentaire", "gain": 0, "applique": False,
                      "detail": "Le rattachement (demi-part, plafonnée) est retenu. Si l'enfant a peu de revenus et votre tranche est ≥ 30 %, déduire une pension (jusqu'à environ 6 800 € par enfant) peut être plus avantageux : l'agent peut simuler les deux si vous indiquez les revenus de l'enfant."})
    taux = val.get("avis_taux_pas") or p.get("taux_pas")
    rev_imp = (val.get("salaires") or 0) + (val.get("salaires_d2") or 0) + (val.get("pensions") or 0) + (val.get("pensions_d2") or 0)
    deja = round(rev_imp * float(taux) / 100) if taux else 0
    calc = tax.impot_revenu({**d, "pas_verse": deja}, year)
    by_case = {v[1]: k for k, v in tax.CASES.items()}
    for lst in calc["formulaires"].values():
        for x in lst:
            k = by_case.get(x["case"])
            x["source"] = src.get(k) or ("calcul de l'agent" if x["case"] in ("1AK", "1BK", "2OP", "7EA", "7EC", "7EF") or x["case"].startswith("4B") else "")
    checks = controls(p, val, src, sal_banque, year)
    pieces = checklist(con, eid, p, val, year)
    forms = extra_forms(p, val)
    ready = sum(1 for x in pieces if x["recu"]) / len(pieces) if pieces else 1
    statut = "prete" if ready >= 1 and not any(c["niveau"] == "bloquant" for c in checks) else "a_completer"
    return {"annee": year, "statut": statut, "completude": round(ready * 100), "parts": parts, "parts_detail": parts_detail,
            "donnees": {k: {"valeur": v, "source": src.get(k)} for k, v in val.items()}, "calcul": calc, "optimisations": optim,
            "gain_total": sum(o["gain"] for o in optim if o["applique"]), "controles": checks, "pieces": pieces, "formulaires_annexes": forms,
            "foncier": fon["detail"] if fon else None, "automatique": auto_eligible(p, val, fon, forms), "echeances": P.deadlines("particulier", p, year + 1)[:3],
            "taux_pas_utilise": taux}

def choose_foncier(d, biens, deficits_ant, year):
    loyers = sum(float(b.get("loyers") or 0) for b in biens)
    reel = foncier.compute(biens, deficits_ant)
    micro_ok = loyers <= 15000
    t_reel = tax.impot_revenu({**d, "foncier_reel": reel["revenu_imposable"], "deficit_foncier_rg": reel["deficit_revenu_global"]}, year)["total_a_payer"]
    t_micro = tax.impot_revenu({**d, "loyers_micro_foncier": loyers}, year)["total_a_payer"] if micro_ok else None
    if micro_ok and t_micro <= t_reel:
        return {"entrees": {"loyers_micro_foncier": loyers}, "detail": {"regime": "micro-foncier", "loyers": loyers, "abattement": round(loyers * .3)},
                "optimisation": {"titre": "Micro-foncier (abattement de 30 %)", "gain": round(t_reel - t_micro), "applique": True,
                                 "detail": f"Plus avantageux que le réel ({round(t_reel - t_micro)} € d'économie). Case 4BE."}}
    return {"entrees": {"foncier_reel": reel["revenu_imposable"], "deficit_foncier_rg": reel["deficit_revenu_global"], "cases_foncier": reel["cases_2042"]},
            "detail": {"regime": "réel (2044)", **reel},
            "optimisation": {"titre": "Régime réel des revenus fonciers (2044)", "gain": round((t_micro or t_reel) - t_reel), "applique": True,
                             "detail": ("Charges et intérêts supérieurs à l'abattement de 30 % : le réel est plus avantageux." if micro_ok
                                        else "Loyers supérieurs à 15 000 € : régime réel obligatoire.") + " Option pour le réel valable 3 ans."}}

def controls(p, val, src, sal_banque, year):
    out = []
    add = lambda lvl, msg: out.append({"niveau": lvl, "message": msg})
    if p.get("activite") in ("salarie", "dirigeant") and not val.get("salaires"):
        add("bloquant", "Salaire du déclarant 1 manquant : importez le bulletin de décembre ou indiquez le net imposable annuel.")
    if sal_banque and val.get("salaires") and src.get("salaires") != "profil":
        if sal_banque > val["salaires"] * 1.05:
            add("info", f"Salaires reçus sur le compte ({sal_banque:,.0f} €) supérieurs au net imposable : normal si des remboursements de frais ou primes exonérées ont été versés.".replace(",", " "))
    if val.get("salaires") and src.get("salaires") == "profil":
        add("attention", "Le salaire provient d'une estimation : le montant exact figure sur le bulletin de décembre (pré-rempli par l'administration).")
    if val.get("dons", 0) + val.get("dons_aide", 0) > 0 and not any(s.startswith("document") for k, s in src.items() if k.startswith("dons")):
        add("attention", "Conservez les reçus fiscaux de vos dons : ils peuvent être demandés en cas de contrôle.")
    if "etranger" in (p.get("placements") or []) or (p.get("comptes_etrangers") or 0) > 0:
        add("bloquant", f"Déclarez vos {p.get('comptes_etrangers') or ''} compte(s) à l'étranger sur le formulaire 3916 (amende de 1 500 € par compte non déclaré).")
    if p.get("crypto_cessions"):
        add("bloquant", "Cessions de cryptoactifs : formulaire 2086 obligatoire (plus-value = prix de cession − prix d'acquisition × prix de cession / valeur du portefeuille).")
    if p.get("location_type") in ("meublee", "les_deux"):
        add("attention", "Location meublée (LMNP) : revenus à déclarer en BIC sur la 2042-C-PRO (micro-BIC 50 % ou réel avec amortissements, souvent plus avantageux).")
    return out

def checklist(con, eid, p, val, year):
    have = {d["type"] for d in list_documents(con, eid, year)}
    items = [("avis_impot", "Avis d'impôt de l'année précédente (plafond PER, déficits reportables, taux PAS)", True)]
    if p.get("activite") in ("salarie", "dirigeant"):
        items.append(("bulletin_decembre", "Bulletin de salaire de décembre (déclarant 1)", True))
    if p.get("conjoint_activite") in ("salarie", "dirigeant"):
        items.append(("bulletin_decembre", "Bulletin de salaire de décembre (déclarant 2)", True))
    if "retraite" in (p.get("activite"), p.get("conjoint_activite")):
        items.append(("attestation_pension", "Attestation fiscale des caisses de retraite", True))
    if "chomage" in (p.get("activite"), p.get("conjoint_activite")):
        items.append(("attestation_chomage", "Attestation France Travail", True))
    if any(x in (p.get("placements") or []) for x in ("cto", "pea", "scpi", "assurance_vie")):
        items.append(("ifu", "IFU de chaque banque / assureur (reçu en février)", True))
    if val.get("emploi_domicile"):
        items.append(("attestation_emploi_domicile", "Attestation fiscale CESU / organisme de services à la personne", True))
    if val.get("garde_enfants"):
        items.append(("attestation_garde", "Attestation de la crèche ou récapitulatif Pajemploi", True))
    if val.get("dons") or val.get("dons_aide"):
        items.append(("recu_don", "Reçus fiscaux des dons", True))
    if p.get("immobilier_locatif"):
        items.append(("releve_charges_locatif", "Relevé annuel de gestion / charges des biens loués", True))
        if p.get("credit_immo_locatif"):
            items.append(("tableau_amortissement", "Tableau d'amortissement du prêt locatif (intérêts de l'année)", True))
    seen, out = {}, []
    for t, lab, req in items:
        seen[t] = seen.get(t, 0) + 1
        n = sum(1 for d in list_documents(con, eid, year) if d["type"] == t)
        out.append({"type": t, "piece": lab, "obligatoire": req, "recu": n >= seen[t]})
    return out

def extra_forms(p, val):
    forms = []
    if val.get("micro_bnc") or val.get("micro_bic_service") or val.get("micro_bic_vente") or p.get("location_type") in ("meublee", "les_deux"):
        forms.append({"formulaire": "2042-C-PRO", "objet": "Revenus des professions non salariées / location meublée"})
    if p.get("immobilier_locatif") and p.get("location_type") in ("nue", "les_deux"):
        forms.append({"formulaire": "2044", "objet": "Revenus fonciers au régime réel (si retenu)"})
    if any(k in val for k in ("dons", "dons_aide", "emploi_domicile", "garde_enfants", "ehpad")):
        forms.append({"formulaire": "2042-RICI", "objet": "Réductions et crédits d'impôt"})
    if "etranger" in (p.get("placements") or []) or (p.get("comptes_etrangers") or 0):
        forms.append({"formulaire": "3916-3916 bis", "objet": "Comptes et contrats détenus à l'étranger (dont plateformes crypto)"})
    if p.get("crypto_cessions"):
        forms.append({"formulaire": "2086", "objet": "Plus-values de cession d'actifs numériques"})
    return forms

def auto_eligible(p, val, fon, forms):
    """Déclaration automatique : possible si seuls des revenus pré-remplis existent et que la situation n'a pas changé."""
    extra = forms or fon or any(val.get(k) for k in ("dons", "dons_aide", "emploi_domicile", "garde_enfants", "per_versements", "pension_alimentaire", "frais_reels", "ehpad"))
    ok = not extra and not p.get("situation_changement") and p.get("activite") in ("salarie", "retraite", "chomage")
    return {"eligible": bool(ok), "explication": ("Votre situation semble éligible à la déclaration automatique : si les montants pré-remplis par l'administration sont exacts, vous n'avez rien à faire."
                                                  if ok else "Vous devez déposer une déclaration : certaines informations (réductions, revenus non pré-remplis, options) doivent être ajoutées.")}

# ---------------- Dépôt ----------------
SCREENS = [
    ("Connexion", "impots.gouv.fr › Espace particulier › « Déclarer mes revenus ». Connectez-vous avec votre numéro fiscal ou FranceConnect."),
    ("Étape 1 — Informations personnelles", "Vérifiez l'état civil, l'adresse et la situation de famille ({situation}, {parts} parts)."),
    ("Étape 2 — Sélection des rubriques", "Cochez les rubriques : {rubriques}."),
    ("Étape 3 — Revenus et charges", "Saisissez ou corrigez les cases ci-dessous, une par une."),
    ("Étape 4 — Récapitulatif", "L'administration affiche une estimation : elle doit être proche de {total} € (écart > 5 % : vérifier une case)."),
    ("Signature", "Signez la déclaration et téléchargez l'accusé de réception ; importez-le ici pour l'archiver."),
]

def copilot(decl):
    c = decl["calcul"]
    rub = sorted({f for f in c["formulaires"]} | {x["formulaire"] for x in decl["formulaires_annexes"]})
    steps = []
    for t, txt in SCREENS:
        steps.append({"etape": t, "consigne": txt.format(situation=decl["donnees"].get("situation", {}).get("valeur", ""), parts=c["parts"],
                                                       rubriques=", ".join(rub) or "aucune rubrique supplémentaire", total=c["total_a_payer"])})
    cases = [{"formulaire": form, **x} for form, lst in c["formulaires"].items() for x in lst]
    return {"etapes": steps, "cases": cases}

def submit(con, eid, year, decl):
    from . import edi, filing
    p, _ = P.get(con, eid)
    data = {"formulaires": decl["calcul"]["formulaires"], "annexes": decl["formulaires_annexes"], "numero_fiscal": p.get("numero_fiscal"),
            "calcul": {k: decl["calcul"][k] for k in ("revenu_net_imposable", "total_a_payer", "parts")}}
    out = filing.save_and_submit(con, eid, "ir", str(year), data, submit=True)
    out["copilote"] = copilot(decl)
    return out

def ai_review(decl, p):
    """Relecture par Claude : options oubliées, incohérences, questions à poser."""
    sys = ("Tu es un fiscaliste français expérimenté. Relis cette déclaration de revenus préparée automatiquement. Liste les erreurs possibles, "
           "les optimisations légales oubliées et les questions à poser au contribuable. Sois précis (cases, articles du CGI) et concis. "
           'Réponds UNIQUEMENT en JSON : {"remarques": [{"niveau": "info|attention|bloquant", "message": "..."}]}')
    res = ai._json(ai.llm(sys, json.dumps({"profil": {k: v for k, v in p.items() if not k.startswith("_")}, "declaration": decl}, ensure_ascii=False, default=str), 1800))
    return (res or {}).get("remarques") if isinstance(res, dict) else None
