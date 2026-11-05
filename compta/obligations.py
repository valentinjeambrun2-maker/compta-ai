"""Centre des obligations déclaratives d'une entreprise : ce qui est dû, quand, pour combien, et dans quel état.
`run` prépare (et transmet si un partenaire EDI est configuré) toutes les déclarations échues d'un coup."""
import json, calendar, datetime as dt
from . import ledger, tax, vat, liasse, payroll, filing, db, profile as P

def _last(y, m):
    return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"

def _status(con, eid, typ, period):
    r = con.execute("SELECT status FROM declarations WHERE entity_id=? AND type=? AND period=? ORDER BY id DESC LIMIT 1", (eid, typ, period)).fetchone()
    return r[0] if r else "a_preparer"

def listing(con, eid, year):
    ent = ledger.entity(con, eid)
    p, _ = P.get(con, eid)
    per = db.get_setting(con, eid, "tva_periodicite") or p.get("tva_regime") or ("franchise" if ent["tva_regime"] == "franchise" else "reel_mensuel")
    today = dt.date.today().isoformat()
    out = []
    def item(typ, label, period, start, end, due, montant=None):
        out.append({"type": typ, "libelle": label, "periode": period, "debut": start, "fin": end, "echeance": due,
                    "statut": _status(con, eid, typ, period), "exigible": end < today, "montant": montant})
    if per in ("reel_mensuel", "reel"):
        for m in range(1, 13):
            s, e = f"{year}-{m:02d}-01", _last(year, m)
            ny, nm = (year + (m == 12), 1 if m == 12 else m + 1)
            d = tax.ca3(con, eid, s, e)
            item("tva", f"TVA {['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre'][m-1]} {year} (CA3)",
                 f"{year}-{m:02d}", s, e, f"{ny}-{nm:02d}-19", (d["a_payer"] or -d["credit"]) or 0)
    elif per == "reel_trimestriel":
        for q in range(4):
            s, e = f"{year}-{3*q+1:02d}-01", _last(year, 3 * q + 3)
            ny, nm = (year + (q == 3), 1 if q == 3 else 3 * q + 4)
            d = tax.ca3(con, eid, s, e)
            item("tva", f"TVA T{q+1} {year} (CA3)", f"{year}-T{q+1}", s, e, f"{ny}-{nm:02d}-19", (d["a_payer"] or -d["credit"]) or 0)
    elif per == "rsi":
        c12 = vat.ca12(con, eid, year)
        item("ca12", f"TVA annuelle {year} (CA12)", str(year), f"{year}-01-01", f"{year}-12-31", f"{year + 1}-05-05", c12["solde"])
    is_soc = ent["legal_form"] in ("SAS", "SASU", "SARL", "EURL", "SA") and p.get("regime_fiscal", "is") == "is"
    if ent["kind"] == "entreprise":
        if is_soc:
            item("liasse", f"Liasse fiscale {year} (2065 + 2033)", str(year), f"{year}-01-01", f"{year}-12-31", f"{year + 1}-05-05")
            # Solde = IS dû sur le résultat fiscal, net des acomptes versés au 444 pendant l'exercice.
            acomptes = con.execute("""SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM lines l JOIN entries en ON en.id = l.entry_id
                WHERE en.entity_id=? AND l.account='444' AND en.source!='closing' AND en.date BETWEEN ? AND ?""",
                (eid, f"{year}-01-01", f"{year}-12-31")).fetchone()[0] / 100
            is_du = liasse.compute(con, eid, year)["2065"]["IS total"]
            item("is", f"Relevé de solde d'IS {year} (2572)", str(year), f"{year}-01-01", f"{year}-12-31", f"{year + 1}-05-15", round(is_du - acomptes, 2))
        months = {r[0] for r in con.execute("SELECT DISTINCT period FROM payslips WHERE entity_id=? AND substr(period,1,4)=?", (eid, str(year)))}
        eff = int(db.get_setting(con, eid, "effectif", 0) or 0)
        for m in sorted(months):
            y_, m_ = int(m[:4]), int(m[5:])
            ny, nm = (y_ + (m_ == 12), 1 if m_ == 12 else m_ + 1)
            item("dsn", f"DSN {m}", m, f"{m}-01", _last(y_, m_), f"{ny}-{nm:02d}-{'05' if eff >= 50 else '15'}")
    for o in out:
        o["en_retard"] = o["echeance"] < today and o["statut"] not in ("deposee", "simulee", "transmise")
    return {"periodicite_tva": per, "obligations": sorted(out, key=lambda o: o["echeance"])}

def prepare(con, eid, o):
    t = o["type"]
    if t == "tva":
        return tax.ca3(con, eid, o["debut"], o["fin"])
    if t == "ca12":
        return vat.ca12(con, eid, int(o["periode"]))
    if t == "liasse":
        return liasse.compute(con, eid, int(o["periode"]))
    if t == "is":
        L = liasse.compute(con, eid, int(o["periode"]))
        return {"2065": L["2065"], "resultat_fiscal": L["resultat_fiscal"]}
    if t == "dsn":
        return payroll.dsn(con, eid, o["periode"])
    raise ledger.LedgerError("Type inconnu")

def run(con, eid, year, only_due=True):
    """Prépare et transmet (si EDI configuré) toutes les déclarations exigibles non encore déposées."""
    done = []
    for o in listing(con, eid, year)["obligations"]:
        if (only_due and not o["exigible"]) or o["statut"] in ("deposee", "simulee", "transmise"):
            continue
        data = prepare(con, eid, o)
        r = filing.save_and_submit(con, eid, o["type"], o["periode"], json.loads(json.dumps(data, default=str)), submit=True)
        done.append({"declaration": o["libelle"], "statut": r["status"], "edi": (r.get("edi") or {}).get("ref"), "erreurs": r["erreurs"]})
    return done
