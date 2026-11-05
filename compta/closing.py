"""Travaux de clôture et de révision : rapprochement bancaire, régularisations (cut-off), extourne,
détermination et affectation du résultat, pièces justificatives."""
import datetime as dt
from . import ledger

E = ledger.euros

# ---------------- Rapprochement bancaire ----------------
def set_statement(con, eid, date, solde_eur, account="512"):
    con.execute("INSERT INTO bank_statements(entity_id,account,date,solde) VALUES(?,?,?,?)", (eid, account, date, ledger.cents(solde_eur)))

def toggle_point(con, eid, line_id, value=None):
    r = con.execute("SELECT l.pointe FROM lines l JOIN entries e ON e.id=l.entry_id WHERE l.id=? AND e.entity_id=?", (line_id, eid)).fetchone()
    if not r:
        raise ledger.LedgerError("Ligne introuvable")
    v = (0 if r[0] else 1) if value is None else int(bool(value))
    con.execute("UPDATE lines SET pointe=? WHERE id=?", (v, line_id))
    return v

def reconciliation(con, eid, date, solde_releve_eur=None, account="512"):
    """État de rapprochement : solde du relevé + encaissements non pointés − décaissements non pointés = solde comptable."""
    if solde_releve_eur in (None, ""):
        r = con.execute("SELECT solde FROM bank_statements WHERE entity_id=? AND account=? AND date<=? ORDER BY date DESC, id DESC LIMIT 1",
                        (eid, account, date)).fetchone()
        releve = r[0] if r else None
    else:
        releve = ledger.cents(solde_releve_eur)
    compta = sum(b["solde"] for b in ledger.balances(con, eid, None, date) if b["account"] == account)
    np = [dict(r) for r in con.execute("""SELECT l.id, e.date, e.label, l.debit, l.credit FROM lines l JOIN entries e ON e.id=l.entry_id
              WHERE e.entity_id=? AND l.account=? AND e.date<=? AND COALESCE(l.pointe,0)=0 ORDER BY e.date""", (eid, account, date))]
    enc = sum(l["debit"] for l in np); dec = sum(l["credit"] for l in np)
    out = {"date": date, "compte": account, "solde_comptable": E(compta), "encaissements_non_pointes": E(enc),
           "decaissements_non_pointes": E(dec), "lignes_non_pointees": [{**l, "debit": E(l["debit"]), "credit": E(l["credit"])} for l in np]}
    if releve is not None:
        theorique = releve + enc - dec
        out.update({"solde_releve": E(releve), "solde_rapproche": E(theorique), "ecart": E(compta - theorique), "equilibre": compta == theorique})
    return out

# ---------------- Extourne ----------------
def reverse_entry(con, eid, entry_id, date=None):
    en = con.execute("SELECT * FROM entries WHERE id=? AND entity_id=?", (entry_id, eid)).fetchone()
    if not en:
        raise ledger.LedgerError("Écriture introuvable")
    if con.execute("SELECT 1 FROM entries WHERE reversal_of=?", (entry_id,)).fetchone():
        raise ledger.LedgerError("Écriture déjà extournée")
    lines = [{"account": l["account"], "debit": l["credit"], "credit": l["debit"], "rate": l["rate"], "base": -(l["base"] or 0) if l["base"] else None}
             for l in con.execute("SELECT * FROM lines WHERE entry_id=?", (entry_id,))]
    nid = ledger.post_entry(con, eid, date or dt.date.today().isoformat(), en["journal"], f"Extourne : {en['label']}", lines, ref=en["ref"], source="extourne")
    con.execute("UPDATE entries SET reversal_of=? WHERE id=?", (entry_id, nid))
    return nid

# ---------------- Régularisations de fin d'exercice ----------------
REGUL = {
    "cca": ("Charge constatée d'avance", "486", "credit_charge"),     # D 486 / C 6xx
    "pca": ("Produit constaté d'avance", "487", "debit_produit"),     # D 7xx / C 487
    "fnp": ("Facture non parvenue", "408", "debit_charge"),           # D 6xx (+ TVA en attente) / C 408
    "fae": ("Facture à établir", "418", "credit_produit"),           # D 418 / C 7xx (+ TVA)
    "cap": ("Charge à payer (congés payés, bonus…)", "428", "debit_charge"),
    "provision": ("Provision pour risques et charges", "151", "debit_charge"),
    "depreciation_client": ("Dépréciation de créance douteuse", "491", "debit_charge"),
}

def regularisation(con, eid, kind, account, amount_eur, year, label="", tva_rate=0, auto_reverse=True):
    """Passe une régularisation au 31/12 et, si demandé, son extourne au 1er janvier suivant."""
    if kind not in REGUL:
        raise ledger.LedgerError("Type de régularisation inconnu")
    name, tiers_acc, mode = REGUL[kind]
    if kind == "provision":
        account = account or "6815"
    if kind == "depreciation_client":
        account = account or "6817"
    if not account:
        raise ledger.LedgerError("Compte de charge ou de produit requis")
    m = ledger.cents(amount_eur)
    tva = round(m * float(tva_rate or 0) / 100)
    e = f"{year}-12-31"
    if mode == "credit_charge":
        lines = [{"account": tiers_acc, "debit": m}, {"account": account, "credit": m}]
    elif mode == "debit_produit":
        lines = [{"account": account, "debit": m}, {"account": tiers_acc, "credit": m}]
    elif mode == "debit_charge":
        lines = [{"account": account, "debit": m}] + ([{"account": "44586", "debit": tva}] if tva else []) + [{"account": tiers_acc, "credit": m + tva}]
    else:
        lines = [{"account": tiers_acc, "debit": m + tva}, {"account": account, "credit": m}] + ([{"account": "4458", "credit": tva}] if tva else [])
    en = ledger.post_entry(con, eid, e, "OD", f"{name} — {label or account}", lines, source="regularisation")
    rev = None
    if auto_reverse and kind not in ("provision", "depreciation_client"):
        rev = reverse_entry(con, eid, en, f"{year + 1}-01-01")
    return {"entry_id": en, "extourne_id": rev}

def suggest_regularisations(con, eid, year):
    """Suggestions automatiques de cut-off : abonnements et assurances annuels payés en fin d'année (CCA),
    factures clients émises d'avance, congés payés, créances clients anciennes."""
    out = []
    for r in con.execute("""SELECT e.date, e.label, l.account, l.debit FROM lines l JOIN entries e ON e.id=l.entry_id
            WHERE e.entity_id=? AND e.date BETWEEN ? AND ? AND l.debit>0 AND (l.account LIKE '616%' OR l.account LIKE '613%' OR l.account LIKE '628%' OR l.account LIKE '6281%')
            AND (lower(e.label) LIKE '%annuel%' OR lower(e.label) LIKE '%assurance%' OR lower(e.label) LIKE '%axa%' OR lower(e.label) LIKE '%loyer%' OR lower(e.label) LIKE '%abonnement%')""",
            (eid, f"{year}-07-01", f"{year}-12-31")):
        d = dt.date.fromisoformat(r["date"])
        mois_restants = 12 - d.month  # prorata : couverture 12 mois à partir du mois de paiement
        if "loyer" in r["label"].lower():
            continue
        if mois_restants > 0:
            cca = round(r["debit"] * mois_restants / 12)
            out.append({"type": "cca", "compte": r["account"], "montant": E(cca), "libelle": f"{r['label']} ({r['date']})",
                        "raison": f"Paiement annuel du {r['date']} : {mois_restants} mois couvrent l'exercice suivant."})
    sal = con.execute("""SELECT COALESCE(SUM(l.debit),0) FROM lines l JOIN entries e ON e.id=l.entry_id WHERE e.entity_id=? AND l.account LIKE '641%'
                         AND e.date BETWEEN ? AND ?""", (eid, f"{year}-01-01", f"{year}-12-31")).fetchone()[0]
    if sal:
        cp = round(sal * 0.10 * 0.35)  # ~10 % des salaires, environ un tiers des droits non pris au 31/12 (estimation)
        out.append({"type": "cap", "compte": "6412", "montant": E(cp), "libelle": "Provision pour congés payés",
                    "raison": "Congés acquis non pris au 31/12 (estimation : à ajuster selon le décompte réel)."})
    for inv in con.execute("SELECT * FROM invoices WHERE entity_id=? AND kind='sale' AND status='open' AND due<?", (eid, f"{year}-09-30")):
        out.append({"type": "depreciation_client", "compte": "6817", "montant": E(round((inv["ht"]) * 0.5)), "libelle": f"Créance {inv['number']} ({inv['party']})",
                    "raison": f"Facture impayée depuis le {inv['due']} : dépréciation de 50 % du HT à envisager (à apprécier selon le risque)."})
    return out

# ---------------- Détermination et affectation du résultat ----------------
def close_result(con, eid, year):
    """Solde les comptes 6 et 7 de l'exercice dans 120 (bénéfice) ou 129 (perte)."""
    s, e = f"{year}-01-01", f"{year}-12-31"
    if con.execute("SELECT 1 FROM entries WHERE entity_id=? AND source=? AND date=?", (eid, ledger.CLOSING, e)).fetchone():
        raise ledger.LedgerError("Résultat de l'exercice déjà déterminé")
    lines, res = [], 0
    for b in ledger.balances(con, eid, s, e, exclude_closing=True):
        if b["account"][0] in "67" and b["solde"]:
            lines.append({"account": b["account"], "debit": -b["solde"]} if b["solde"] < 0 else {"account": b["account"], "credit": b["solde"]})
            res -= b["solde"]
    if not lines:
        return None
    lines.append({"account": "120", "credit": res} if res > 0 else {"account": "129", "debit": -res})
    en = ledger.post_entry(con, eid, e, "OD", f"Détermination du résultat {year}", lines, source=ledger.CLOSING)
    return {"entry_id": en, "resultat": E(res)}

def allocate_result(con, eid, year, date, reserve_legale=None, dividendes=0, report=None):
    """Affectation du résultat de l'exercice (décision d'AG) : réserve légale, dividendes, report à nouveau."""
    r120 = -sum(b["solde"] for b in ledger.balances(con, eid, None, date) if b["account"] == "120")
    r129 = sum(b["solde"] for b in ledger.balances(con, eid, None, date) if b["account"] == "129")
    if r129 > 0:
        return {"entry_id": ledger.post_entry(con, eid, date, "OD", f"Affectation de la perte {year}", [{"account": "119", "debit": r129}, {"account": "129", "credit": r129}], source="affectation")}
    if r120 <= 0:
        raise ledger.LedgerError("Aucun bénéfice à affecter (déterminez d'abord le résultat)")
    capital = -sum(b["solde"] for b in ledger.balances(con, eid, None, date) if b["account"].startswith("101"))
    rl_actuelle = -sum(b["solde"] for b in ledger.balances(con, eid, None, date) if b["account"] == "1061")
    rl = ledger.cents(reserve_legale) if reserve_legale not in (None, "") else max(0, min(round(r120 * .05), round(capital * .10) - rl_actuelle))
    div = ledger.cents(dividendes or 0)
    reste = r120 - rl - div
    if reste < 0:
        raise ledger.LedgerError("Affectation supérieure au bénéfice")
    lines = [{"account": "120", "debit": r120}]
    if rl: lines.append({"account": "1061", "credit": rl})
    if div: lines.append({"account": "457", "credit": div})
    if reste: lines.append({"account": "110" if report is None or report else "1068", "credit": reste})
    en = ledger.post_entry(con, eid, date, "OD", f"Affectation du résultat {year}", lines, source="affectation")
    return {"entry_id": en, "reserve_legale": E(rl), "dividendes": E(div), "report_a_nouveau": E(reste)}

# ---------------- Pièces justificatives ----------------
def attach(con, eid, name, mime, data, entry_id=None, invoice_id=None):
    if entry_id and not con.execute("SELECT 1 FROM entries WHERE id=? AND entity_id=?", (entry_id, eid)).fetchone():
        raise ledger.LedgerError("Écriture introuvable")
    return con.execute("INSERT INTO attachments(entity_id,entry_id,invoice_id,name,mime,data) VALUES(?,?,?,?,?,?)",
                       (eid, entry_id, invoice_id, name, mime, data)).lastrowid
