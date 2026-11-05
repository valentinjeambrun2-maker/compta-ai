"""Notes de frais : saisie avec justificatif (lu par l'IA), indemnités kilométriques, validation et remboursement."""
from . import ledger, documents

# Barème kilométrique voitures (BOFiP, revenus 2024 reconduit en 2025) : cv -> [(jusqu'à km, a, b)] : montant = a × d + b
BAREME_KM = {3: [(5000, .529, 0), (20000, .316, 1065), (None, .370, 0)], 4: [(5000, .606, 0), (20000, .340, 1330), (None, .407, 0)],
             5: [(5000, .636, 0), (20000, .357, 1395), (None, .427, 0)], 6: [(5000, .665, 0), (20000, .374, 1457), (None, .447, 0)],
             7: [(5000, .697, 0), (20000, .394, 1515), (None, .470, 0)]}

# Catégories et règles de TVA récupérable
CATEGORIES = {
    "restaurant": ("6257", 10, True), "carburant": ("625", 20, True), "transport": ("625", 10, False), "hebergement": ("625", 10, False),
    "peage_parking": ("625", 20, True), "fournitures": ("606", 20, True), "logiciel": ("628", 20, True), "telecom": ("626", 20, True),
    "cadeau": ("623", 20, True), "autre": ("628", 20, True),
}

def km_allowance(km, cv, annual_km=None):
    """Indemnité pour un trajet, au taux de la tranche correspondant au kilométrage annuel estimé (≤ 5 000 km par défaut)."""
    cv = max(3, min(7, int(cv or 5)))
    d = float(annual_km or 0)
    for lim, a, b in BAREME_KM[cv]:
        if lim is None or d <= lim:
            return round(float(km) * a, 2)

def create(con, eid, date, person, label, category="autre", ttc=None, tva_rate=None, beneficiaire="dirigeant",
           km=None, cv=None, file_name=None, file_mime=None, file_data=None):
    ledger._check_date(date)
    if km:
        account, rate = "6251", 0.0
        ttc = km_allowance(km, cv)
        label = label or f"Indemnités kilométriques {km} km ({cv} CV)"
    else:
        if ttc in (None, "") or float(ttc) <= 0:
            raise ledger.LedgerError("Montant TTC requis")
        account, default_rate, deductible = CATEGORIES.get(category, CATEGORIES["autre"])
        rate = float(tva_rate) if tva_rate not in (None, "") and deductible else (default_rate if deductible else 0.0)
    return con.execute("""INSERT INTO expenses(entity_id,date,person,beneficiaire,label,account,ttc,tva_rate,km,cv,file_name,file_mime,file_data)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (eid, date, person, beneficiaire, label, account, ledger.cents(ttc), rate, km, cv,
                                                file_name, file_mime, file_data)).lastrowid

def from_receipt(data, mime):
    """Pré-remplit une note de frais depuis la photo / le PDF du justificatif."""
    r = documents.read_document(data, mime)
    lines = r.get("lines") or []
    ttc = r.get("total_ttc") or round(sum(l.get("qty", 1) * l.get("unit_price", 0) * (1 + l.get("tva_rate", 0) / 100) for l in lines), 2)
    cat = r.get("categorie") or "autre"
    return {"date": r.get("date"), "label": r.get("party") or "", "ttc": ttc, "category": cat if cat in CATEGORIES else "autre",
            "tva_rate": (lines[0].get("tva_rate") if lines else None), "source": r.get("source")}

def validate(con, eid, exp_id):
    x = con.execute("SELECT * FROM expenses WHERE id=? AND entity_id=?", (exp_id, eid)).fetchone()
    if not x:
        raise ledger.LedgerError("Note de frais introuvable")
    if x["status"] != "a_valider":
        raise ledger.LedgerError("Note de frais déjà validée")
    ttc, rate = x["ttc"], x["tva_rate"] or 0
    if ledger.entity(con, eid)["tva_regime"] == "franchise":
        rate = 0
    ht = round(ttc / (1 + rate / 100)); tva = ttc - ht
    lines = [{"account": x["account"], "debit": ht}, {"account": "467", "credit": ttc}]
    if tva:
        lines.insert(1, {"account": "44566", "debit": tva, "rate": rate, "base": ht})
    en = ledger.post_entry(con, eid, x["date"], "OD", f"Note de frais {x['person'] or ''} — {x['label']}", lines, ref=f"NDF{exp_id}", source="ndf")
    con.execute("UPDATE expenses SET status='validee', entry_id=? WHERE id=?", (en, exp_id))
    return en

def reimburse(con, eid, exp_ids, date):
    rows = [con.execute("SELECT * FROM expenses WHERE id=? AND entity_id=? AND status='validee'", (i, eid)).fetchone() for i in exp_ids]
    rows = [r for r in rows if r]
    if not rows:
        raise ledger.LedgerError("Aucune note de frais validée à rembourser")
    tot = sum(r["ttc"] for r in rows)
    en = ledger.post_entry(con, eid, date, "BQ", f"Remboursement de {len(rows)} note(s) de frais", [{"account": "467", "debit": tot}, {"account": "512", "credit": tot}], source="ndf")
    for r in rows:
        con.execute("UPDATE expenses SET status='remboursee', pay_entry_id=? WHERE id=?", (en, r["id"]))
    return {"entry_id": en, "total": ledger.euros(tot)}
