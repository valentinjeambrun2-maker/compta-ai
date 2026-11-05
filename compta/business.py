"""Facturation, immobilisations/amortissements, clôture, audit, préparation fiscale."""
import json, datetime as dt, html
from . import ledger, tax

E = ledger.euros

# ---------------- Factures ----------------
def next_number(con, eid, year):
    n = con.execute("SELECT COUNT(*) FROM invoices WHERE entity_id=? AND kind='sale' AND substr(date,1,4)=?", (eid, year)).fetchone()[0]
    return f"FA-{year}-{n + 1:04d}"

def create_invoice(con, eid, kind, party, date, lines, number=None, due=None, account=None, nature="services", email=None, quote_id=None,
                   operation="france", tiers_info=None):
    """TVA sur les encaissements : pour les prestations de services d'une entité qui n'a pas opté pour les débits,
    la TVA est d'abord inscrite en attente (44574 / 44586) puis devient exigible / déductible au règlement."""
    if kind not in ("sale", "purchase"):
        raise ledger.LedgerError("Type de facture invalide")
    if not lines:
        raise ledger.LedgerError("La facture doit avoir au moins une ligne")
    ent = ledger.entity(con, eid)
    from . import tiers as T, vat
    t = T.find_or_create(con, eid, "client" if kind == "sale" else "fournisseur", party, email=email, **(tiers_info or {}))
    if not due:
        due = (dt.date.fromisoformat(date) + dt.timedelta(days=int(t.get("delai_jours") or 30))).isoformat()
    if operation != "france":
        return vat.create_international_invoice(con, eid, kind, t, date, lines, number, due, account, nature, email, quote_id, operation)
    franchise = ent["tva_regime"] == "franchise" and kind == "sale"
    encaiss = (ent.get("tva_exigibilite") == "encaissements" and nature == "services")
    by_rate, out = {}, []
    for l in lines:
        rate = 0.0 if franchise else float(l.get("tva_rate", 20))
        ht = round(float(l.get("qty", 1)) * ledger.cents(l.get("unit_price", 0)))
        by_rate.setdefault(rate, 0)
        by_rate[rate] += ht
        out.append({"label": l.get("label", ""), "qty": float(l.get("qty", 1)), "unit_price": float(l.get("unit_price", 0)), "tva_rate": rate, "ht": ht})
    tvas = {r: round(b * r / 100) for r, b in by_rate.items()}
    ht, tva = sum(by_rate.values()), sum(tvas.values())
    ttc = ht + tva
    if ht <= 0:
        raise ledger.LedgerError("Montant HT nul ou négatif")
    if kind == "sale":
        number = next_number(con, eid, date[:4])  # numérotation chronologique continue obligatoire
        account = account or "706"
        el = [{"account": t["account"], "debit": ttc, "label": f"{number} {party}"}, {"account": account, "credit": ht}]
        el += [{"account": "44574" if encaiss else "44571", "credit": t, "rate": r, "base": by_rate[r]} for r, t in tvas.items() if t]
        jr = "VE"
    else:
        number = number or f"ACH-{date}"
        account = account or "606"
        el = [{"account": account, "debit": ht}]
        el += [{"account": "44586" if encaiss else "44566", "debit": t, "rate": r, "base": by_rate[r]} for r, t in tvas.items() if t]
        el.append({"account": t["account"], "credit": ttc, "label": f"{number} {party}"})
        jr = "AC"
    en = ledger.post_entry(con, eid, date, jr, f"Facture {number} — {party}", el, ref=number, source="invoice")
    return save_invoice(con, eid, kind, number, date, due, party, ht, tva, ttc, out, account, en, nature, email, quote_id, t, "france")

def save_invoice(con, eid, kind, number, date, due, party, ht, tva, ttc, out, account, en, nature, email, quote_id, t, operation):
    cur = con.execute("""INSERT INTO invoices(entity_id,kind,number,date,due,party,ht,tva,ttc,lines,account,entry_id,nature,email,quote_id,
                         tiers_id,tiers_account,operation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (eid, kind, number, date, due, party, ht, tva, ttc, json.dumps(out), account, en, nature, email or t.get("email"), quote_id,
                       t["id"], t["account"], operation))
    return cur.lastrowid

def tiers_account(inv):
    return inv["tiers_account"] or ("411" if inv["kind"] == "sale" else "401")

def letter_invoice(con, eid, inv_id, pay_entry):
    """Lettre la ligne de tiers de la facture avec celle du règlement."""
    from . import tiers as T
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
    acc = tiers_account(inv)
    ids = [r[0] for r in con.execute("SELECT id FROM lines WHERE entry_id IN (?,?) AND account=? AND lettrage IS NULL", (inv["entry_id"], pay_entry, acc))]
    if len(ids) == 2:
        try:
            T.letter(con, eid, ids)
        except ledger.LedgerError:
            pass

def pay_invoice(con, eid, inv_id, date=None):
    inv = con.execute("SELECT * FROM invoices WHERE id=? AND entity_id=?", (inv_id, eid)).fetchone()
    if not inv:
        raise ledger.LedgerError("Facture introuvable")
    if inv["status"] == "paid":
        raise ledger.LedgerError("Facture déjà réglée")
    date = date or dt.date.today().isoformat()
    if inv["kind"] == "sale":
        lines = [{"account": "512", "debit": inv["ttc"]}, {"account": tiers_account(inv), "credit": inv["ttc"]}]
    else:
        lines = [{"account": tiers_account(inv), "debit": inv["ttc"]}, {"account": "512", "credit": inv["ttc"]}]
    en = ledger.post_entry(con, eid, date, "BQ", f"Règlement {inv['number']} — {inv['party']}", lines, ref=inv["number"], source="invoice")
    con.execute("UPDATE invoices SET status='paid', pay_entry_id=? WHERE id=?", (en, inv_id))
    letter_invoice(con, eid, inv_id, en)
    on_invoice_paid(con, eid, inv_id, date)
    return en

def on_invoice_paid(con, eid, inv_id, date):
    """Bascule la TVA en attente (régime des encaissements) vers la TVA exigible / déductible à la date du règlement."""
    inv = con.execute("SELECT * FROM invoices WHERE id=? AND entity_id=?", (inv_id, eid)).fetchone()
    pend = con.execute("SELECT account, debit, credit, rate, base FROM lines WHERE entry_id=? AND account IN ('44574','44586')",
                       (inv["entry_id"],)).fetchall()
    if not pend:
        return None
    lines = []
    for l in pend:
        if l["account"] == "44574":
            lines += [{"account": "44574", "debit": l["credit"]}, {"account": "44571", "credit": l["credit"], "rate": l["rate"], "base": l["base"]}]
        else:
            lines += [{"account": "44566", "debit": l["debit"], "rate": l["rate"], "base": l["base"]}, {"account": "44586", "credit": l["debit"]}]
    return ledger.post_entry(con, eid, date, "OD", f"TVA exigible à l'encaissement — {inv['number']}", lines, ref=inv["number"], source="tva")

def invoice_html(con, eid, inv_id):
    inv = dict(con.execute("SELECT * FROM invoices WHERE id=? AND entity_id=?", (inv_id, eid)).fetchone())
    ent = ledger.entity(con, eid)
    h = html.escape
    rows = "".join(f"<tr><td>{h(l['label'])}</td><td>{l['qty']:g}</td><td>{l['unit_price']:.2f} €</td><td>{l['tva_rate']:g} %</td><td>{l['ht']/100:.2f} €</td></tr>"
                   for l in json.loads(inv["lines"]))
    franchise = "<p><em>TVA non applicable, art. 293 B du CGI.</em></p>" if ent["tva_regime"] == "franchise" else ""
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8"><title>{h(inv['number'])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;color:#111;padding:0 16px}}table{{width:100%;border-collapse:collapse}}
td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}.tot td{{font-weight:600}}small{{color:#555}}</style>
<h1>Facture {h(inv['number'])}</h1>
<p><strong>{h(ent['name'])}</strong><br>{h(ent.get('address') or '')}<br>SIRET : {h(ent.get('siret') or '—')}</p>
<p>Client : <strong>{h(inv['party'])}</strong><br>Date : {inv['date']} — Échéance : {inv['due']}</p>
<table><tr><th>Désignation</th><th>Qté</th><th>PU HT</th><th>TVA</th><th>Total HT</th></tr>{rows}
<tr class="tot"><td colspan="4">Total HT</td><td>{inv['ht']/100:.2f} €</td></tr>
<tr class="tot"><td colspan="4">TVA</td><td>{inv['tva']/100:.2f} €</td></tr>
<tr class="tot"><td colspan="4">Total TTC</td><td>{inv['ttc']/100:.2f} €</td></tr></table>{franchise}
<p><small>Paiement à réception ou à l'échéance indiquée. En cas de retard : pénalités au taux de 3 fois le taux d'intérêt légal
et indemnité forfaitaire pour frais de recouvrement de 40 € (art. L441-10 et D441-5 du Code de commerce). Pas d'escompte pour paiement anticipé.</small></p>
<script>window.print&&setTimeout(()=>0,0)</script></html>"""

# ---------------- Immobilisations ----------------
def add_asset(con, eid, label, date, cost_eur, years, pay_now=True, tva_rate=0):
    """Acquisition d'immobilisation. cost_eur est le coût HT (base d'amortissement) ; la TVA déductible va au 44562.
    Sans TVA pour une franchise en base ou un particulier."""
    cost = ledger.cents(cost_eur)
    ent = ledger.entity(con, eid)
    rate = float(tva_rate or 0) if ent["kind"] == "entreprise" and ent["tva_regime"] != "franchise" else 0.0
    tva = round(cost * rate / 100)
    lines = [{"account": "2183", "debit": cost}, {"account": "512" if pay_now else "401", "credit": cost + tva}]
    if tva:
        lines.insert(1, {"account": "44562", "debit": tva, "rate": rate, "base": cost})
    ledger.post_entry(con, eid, date, "AC", f"Acquisition immobilisation : {label}", lines, source="asset")
    return con.execute("INSERT INTO assets(entity_id,label,date,cost,years) VALUES(?,?,?,?,?)", (eid, label, date, cost, int(years))).lastrowid

def depreciate(con, eid, year):
    """Amortissement linéaire prorata temporis (mois entiers) jusqu'au 31/12 de l'année."""
    total, details = 0, []
    for a in con.execute("SELECT * FROM assets WHERE entity_id=? AND last_year<?", (eid, year)).fetchall():
        d = dt.date.fromisoformat(a["date"])
        if d.year > year:
            continue
        months = (year - d.year) * 12 + (12 - d.month + 1)
        cumul = min(a["cost"], round(a["cost"] * months / (a["years"] * 12)))
        dot = cumul - a["amortized"]
        if dot > 0:
            ledger.post_entry(con, eid, f"{year}-12-31", "OD", f"Dotation amortissement {year} : {a['label']}",
                              [{"account": "681", "debit": dot}, {"account": "281", "credit": dot}], source="closing")
            total += dot
            details.append({"bien": a["label"], "dotation": E(dot)})
        con.execute("UPDATE assets SET amortized=?, last_year=? WHERE id=?", (cumul, year, a["id"]))
    return {"total": E(total), "details": details}

def close_year(con, eid, year, pme=True):
    """Clôture : amortissements, IS (si société), verrouillage de l'exercice."""
    ent = ledger.entity(con, eid)
    out = {"amortissements": depreciate(con, eid, year) if ent["kind"] == "entreprise" else None}
    s, e = f"{year}-01-01", f"{year}-12-31"
    if ent["kind"] == "entreprise" and ent["legal_form"] in ("SAS", "SASU", "SARL", "EURL", "SA"):
        from . import liasse
        # L'IS est dû sur le résultat fiscal (même calcul que la 2065) et se comptabilise au 444, jamais à la TVA (44551).
        isr = tax.impot_societes(liasse.compute(con, eid, year, pme=pme)["2065"]["Résultat fiscal"], pme, year)
        if isr["is"] > 0:
            ledger.post_entry(con, eid, e, "OD", f"Impôt sur les sociétés {year}",
                              [{"account": "695", "debit": int(isr["is"]) * 100}, {"account": "444", "credit": int(isr["is"]) * 100}], source="closing")
        out["impot_societes"] = isr
    if ent["kind"] == "entreprise":
        from . import closing
        out["determination_resultat"] = closing.close_result(con, eid, year)
    con.execute("UPDATE entities SET closed_until=? WHERE id=?", (e, eid))
    out["verrouille_jusqu_au"] = e
    return out

def corriger_is(con, eid, year):
    """Reclasse un IS comptabilisé au 44551 (TVA) vers le 444 (IS), par une écriture de correction.
    L'écriture d'origine n'est pas modifiée. La correction est datée du premier jour ouvert. Sans effet si déjà faite."""
    motif = f"Reclassement IS {year} : 44551 vers 444"
    if con.execute("SELECT 1 FROM entries WHERE entity_id=? AND source='correction_is' AND label=?", (eid, motif)).fetchone():
        return {"montant_eur": 0, "deja_fait": True}
    montant = con.execute("""SELECT COALESCE(SUM(l.credit - l.debit), 0) FROM lines l JOIN entries en ON en.id = l.entry_id
        WHERE en.entity_id=? AND en.source='closing' AND en.label=? AND l.account='44551'""",
        (eid, f"Impôt sur les sociétés {year}")).fetchone()[0]
    if montant <= 0:
        return {"montant_eur": 0, "deja_fait": False}
    ent = ledger.entity(con, eid)
    day = dt.date.today()
    if ent["closed_until"] and day.isoformat() <= ent["closed_until"]:
        day = dt.date.fromisoformat(ent["closed_until"]) + dt.timedelta(days=1)
    ledger.post_entry(con, eid, day.isoformat(), "OD", motif,
                      [{"account": "44551", "debit": montant}, {"account": "444", "credit": montant}], source="correction_is")
    return {"montant_eur": montant / 100, "deja_fait": False, "date": day.isoformat()}

# ---------------- Contexte, audit, préparation fiscale ----------------
def context(con, eid, year):
    ent = ledger.entity(con, eid)
    s, e = f"{year}-01-01", f"{year}-12-31"
    inc = ledger.income_statement(con, eid, s, e)
    ctx = {"dossier": ent["name"], "type": ent["kind"], "forme": ent["legal_form"], "exercice": year,
           "produits": E(inc["total_produits"]), "charges": E(inc["total_charges"]), "resultat": E(inc["resultat"]),
           "tresorerie": E(ledger.solde(con, eid, "512") + ledger.solde(con, eid, "530")),
           "postes_charges": {c["label"]: E(c["montant"]) for c in inc["charges"]},
           "postes_produits": {p["label"]: E(p["montant"]) for p in inc["produits"]},
           "operations_a_valider": con.execute("SELECT COUNT(*) FROM bank_tx WHERE entity_id=? AND status='pending'", (eid,)).fetchone()[0]}
    if ent["kind"] == "entreprise":
        ctx["tva"] = {k: v for k, v in tax.ca3(con, eid, s, e).items() if k in ("collectee", "deductible", "a_payer", "credit")}
        ctx["clients_a_encaisser"] = E(ledger.solde(con, eid, "411"))
        ctx["fournisseurs_a_payer"] = E(-ledger.solde(con, eid, "401"))
        if ent["legal_form"] in ("SAS", "SASU", "SARL", "EURL", "SA"):
            ctx["impot_estime"] = f"IS ≈ {tax.impot_societes(inc['resultat'] / 100, True, year)['is']} €"
        else:
            ctx["impot_estime"] = "Entreprise individuelle : bénéfice imposé à l'IR du dirigeant (voir onglet Impôts)."
    else:
        ctx["impot_estime"] = f"IR ≈ {prepare_ir(con, eid, year)['calcul']['total_a_payer']} €"
    return ctx

def prepare_ir(con, eid, year, profile=None):
    """Pré-remplit la déclaration 2042 à partir des catégories du compte (particulier)."""
    s, e = f"{year}-01-01", f"{year}-12-31"
    b = {x["account"]: x["solde"] for x in ledger.balances(con, eid, s, e)}
    rev = lambda c: max(0, -b.get(c, 0)) / 100
    dep = lambda c: max(0, b.get(c, 0)) / 100
    auto = {"salaires": rev("700"), "pensions": rev("701"), "loyers_micro_foncier": rev("710"), "micro_bnc": rev("711"),
            "micro_bic_service": rev("712"), "interets": rev("720"), "dons": dep("660"), "garde_enfants": dep("670"),
            "emploi_domicile": dep("680")}
    d = {k: v for k, v in auto.items() if v}
    d.update({k: v for k, v in (profile or {}).items() if v not in (None, "")})
    return {"donnees": d, "source_auto": {k: v for k, v in auto.items() if v}, "calcul": tax.impot_revenu(d, year),
            "avertissement": "Les relevés bancaires montrent des montants NETS versés : le salaire net imposable figure sur votre "
                             "bulletin de décembre / attestation employeur et doit primer sur l'estimation bancaire."}

def audit(con, eid, year):
    """Contrôles automatiques type « revue d'expert-comptable »."""
    s, e = f"{year}-01-01", f"{year}-12-31"
    ent, today = ledger.entity(con, eid), dt.date.today().isoformat()
    alerts = []
    add = lambda lvl, msg: alerts.append({"niveau": lvl, "message": msg})
    tb = ledger.trial_balance(con, eid)
    if tb["total_debit"] != tb["total_credit"]:
        add("critique", "La balance générale n'est pas équilibrée.")
    n = con.execute("SELECT COUNT(*) FROM bank_tx WHERE entity_id=? AND status='pending'", (eid,)).fetchone()[0]
    if n:
        add("attention", f"{n} opération(s) bancaire(s) en attente de validation.")
    att = ledger.solde(con, eid, "471")
    if att:
        add("attention", f"Le compte d'attente 471 présente un solde de {ledger.fr(att)} : opérations à recatégoriser.")
    bank = ledger.solde(con, eid, "512")
    if bank < 0:
        add("attention", f"Solde bancaire comptable négatif ({ledger.fr(bank)}) : vérifier le rapprochement ou un découvert.")
    if ent["kind"] == "entreprise":
        for inv in con.execute("SELECT number,party,ttc,due FROM invoices WHERE entity_id=? AND kind='sale' AND status='open' AND due<?", (eid, today)):
            add("attention", f"Facture {inv['number']} ({inv['party']}, {ledger.fr(inv['ttc'])}) échue depuis le {inv['due']} : relancer le client.")
        nums = sorted(int(r[0].split("-")[-1]) for r in con.execute("SELECT number FROM invoices WHERE entity_id=? AND kind='sale' AND substr(date,1,4)=?", (eid, str(year))))
        if nums and nums != list(range(1, len(nums) + 1)):
            add("critique", "Rupture dans la numérotation des factures de vente (obligation de séquence continue).")
        resto = ledger.solde(con, eid, "6257", s, e)
        prod = -ledger.solde(con, eid, "7", s, e)
        if prod and resto > 0.05 * prod:
            add("info", f"Frais de réception élevés ({ledger.fr(resto)}, > 5 % du CA) : conserver les justificatifs et le nom des invités.")
        ca = prod / 100
        if ent["tva_regime"] == "franchise" and ca > 37500:
            add("critique", f"CA de {ledger.fr(prod)} : seuil de franchise en base de TVA probablement dépassé — vérifier les seuils en vigueur.")
        big = con.execute("""SELECT e.label, l.debit FROM lines l JOIN entries e ON e.id=l.entry_id WHERE e.entity_id=? AND l.account LIKE '6%'
                             AND l.debit>50000 AND l.account IN ('606','628') AND e.date BETWEEN ? AND ?""", (eid, s, e)).fetchall()
        for r in big:
            add("info", f"« {r['label']} » ({ledger.fr(r['debit'])} HT) en charge : s'il s'agit d'un bien durable > 500 € HT, l'immobiliser.")
    if not alerts:
        add("ok", "Aucune anomalie détectée.")
    return alerts
