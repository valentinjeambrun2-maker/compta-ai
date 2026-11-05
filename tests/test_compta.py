import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("ANTHROPIC_API_KEY", None)
from compta import db, pcg, ledger, bank, tax, business, filing, tiers, vat
import demo

def new(kind="entreprise", **kw):
    c = db.connect(":memory:")
    e = c.execute("INSERT INTO entities(name,kind,legal_form,tva_regime) VALUES(?,?,?,?)",
                  ("T", kind, kw.get("form", "SASU"), kw.get("tva", "reel"))).lastrowid
    pcg.seed(c, e, kind)
    return c, e

class Ledger(unittest.TestCase):
    def test_cents(self):
        for s, v in (("1 234,56", 123456), ("1.234,56", 123456), ("1,234.56", 123456), ("-12.3", -1230), ("0,005", 1), (12, 1200)):
            self.assertEqual(ledger.cents(s), v)

    def test_unbalanced_rejected(self):
        c, e = new()
        with self.assertRaises(ledger.LedgerError):
            ledger.post_entry(c, e, "2026-01-01", "OD", "x", [{"account": "512", "debit": 100}, {"account": "101", "credit": 99}])
        with self.assertRaises(ledger.LedgerError):
            ledger.post_entry(c, e, "2026-01-01", "OD", "x", [{"account": "999", "debit": 100}, {"account": "101", "credit": 100}])

    def test_closed_period(self):
        c, e = new()
        business.close_year(c, e, 2025)
        with self.assertRaises(ledger.LedgerError):
            ledger.post_entry(c, e, "2025-06-01", "OD", "x", [{"account": "512", "debit": 1}, {"account": "101", "credit": 1}])

class Flows(unittest.TestCase):
    def test_demo_balanced_and_bilan(self):
        c = db.connect(":memory:")
        demo.load(c)
        for (eid,) in c.execute("SELECT id FROM entities"):
            bank.validate_confident(c, eid, 0)
            tb = ledger.trial_balance(c, eid)
            self.assertEqual(tb["total_debit"], tb["total_credit"])
            self.assertTrue(ledger.balance_sheet(c, eid)["equilibre"])

    def test_invoice_and_tva(self):
        c, e = new()
        i = business.create_invoice(c, e, "sale", "Client", "2026-03-01", [{"label": "a", "qty": 2, "unit_price": 100, "tva_rate": 20},
                                                                          {"label": "b", "qty": 1, "unit_price": 50, "tva_rate": 10}])
        business.create_invoice(c, e, "purchase", "Fourn", "2026-03-02", [{"label": "x", "qty": 1, "unit_price": 100, "tva_rate": 20}])
        d = tax.ca3(c, e, "2026-03-01", "2026-03-31")
        self.assertEqual(d["collectee"], 45.0)  # 40 + 5
        self.assertEqual(d["deductible"], 20.0)
        self.assertEqual(d["a_payer"], 25.0)
        self.assertEqual(d["lignes"]["08 Taux normal 20 % — base HT"], 200.0)
        tax.post_tva_settlement(c, e, "2026-03-01", "2026-03-31")
        self.assertEqual(ledger.solde(c, e, "44551"), -2500)
        self.assertEqual(ledger.solde(c, e, "4457"), 0)
        business.pay_invoice(c, e, i, "2026-03-15")
        self.assertEqual(ledger.solde(c, e, "411"), 0)
        n2 = business.create_invoice(c, e, "sale", "C2", "2026-04-01", [{"label": "a", "qty": 1, "unit_price": 10}])
        self.assertEqual(c.execute("SELECT number FROM invoices WHERE id=?", (n2,)).fetchone()[0], "FA-2026-0002")

    def test_bank_import_dedupe_and_tva_split(self):
        c, e = new()
        csv = "Date;Libellé;Montant\n01/02/2026;CB SNCF;-120,00\n01/02/2026;CB SNCF;-120,00\n"
        self.assertEqual(bank.import_rows(c, e, bank.parse_csv(csv))["imported"], 2)
        self.assertEqual(bank.import_rows(c, e, bank.parse_csv(csv))["imported"], 0)
        tx = c.execute("SELECT id FROM bank_tx").fetchone()[0]
        bank.validate(c, e, tx)
        self.assertEqual(ledger.solde(c, e, "625"), 12000)   # transport de personnes : TVA non déductible
        self.assertEqual(ledger.solde(c, e, "44566"), 0)
        bank.import_rows(c, e, bank.parse_csv("Date;Libellé;Montant\n02/02/2026;PRLV OVH CLOUD;-120,00\n"))
        bank.validate(c, e, c.execute("SELECT id FROM bank_tx WHERE label LIKE '%OVH%'").fetchone()[0])
        self.assertEqual(ledger.solde(c, e, "626"), 10000)
        self.assertEqual(ledger.solde(c, e, "44566"), 2000)

    def test_bank_lettrage(self):
        c = db.connect(":memory:")
        demo.load(c)
        tx = c.execute("SELECT * FROM bank_tx WHERE label LIKE '%ACME%'").fetchone()
        self.assertEqual(tx["account"], "411ACMESA")       # compte auxiliaire du client
        bank.validate(c, 1, tx["id"])
        lt = [l["lettrage"] for l in tiers.open_lines(c, 1, "411ACMESA")]
        self.assertEqual(lt, ["AA", "AA"])                  # facture et règlement lettrés
        self.assertEqual(c.execute("SELECT status FROM invoices WHERE number='FA-2026-0001'").fetchone()[0], "paid")
        self.assertEqual(ledger.income_statement(c, 1)["total_produits"], 650000)  # pas de double comptage : 5000 + 1500 HT (+ Stripe non validé)

    def test_depreciation(self):
        c, e = new()
        business.add_asset(c, e, "PC", "2026-07-10", 3600, 3)
        self.assertEqual(business.depreciate(c, e, 2026)["total"], 600.0)   # 6 mois / 36
        self.assertEqual(business.depreciate(c, e, 2026)["total"], 0)       # idempotent
        self.assertEqual(business.depreciate(c, e, 2027)["total"], 1200.0)

    def test_fec(self):
        c = db.connect(":memory:")
        demo.load(c)
        lines = ledger.fec(c, 1, 2026).splitlines()
        self.assertEqual(len(lines[0].split("\t")), 18)
        self.assertTrue(all(len(l.split("\t")) == 18 for l in lines))

class NewFeatures(unittest.TestCase):
    def test_tva_encaissements(self):
        c, e = new()
        c.execute("UPDATE entities SET tva_exigibilite='encaissements' WHERE id=?", (e,))
        i = business.create_invoice(c, e, "sale", "Cli", "2026-03-05", [{"label": "Conseil", "qty": 1, "unit_price": 1000}])
        self.assertEqual(tax.ca3(c, e, "2026-03-01", "2026-03-31")["collectee"], 0)
        business.pay_invoice(c, e, i, "2026-04-10")
        self.assertEqual(tax.ca3(c, e, "2026-04-01", "2026-04-30")["collectee"], 200.0)
        self.assertEqual(ledger.solde(c, e, "44574"), 0)

    def test_payroll_balanced_and_once(self):
        from compta import payroll
        c, e = new()
        c.execute("INSERT INTO employees(entity_id,nom,prenom,brut,date_entree) VALUES(?,?,?,?,?)", (e, "D", "A", 300000, "2025-01-01"))
        self.assertEqual(len(payroll.run_payroll(c, e, "2026-03")), 1)
        self.assertEqual(payroll.run_payroll(c, e, "2026-03"), [])
        tb = ledger.trial_balance(c, e)
        self.assertEqual(tb["total_debit"], tb["total_credit"])
        b = payroll.compute({"brut": 3000}, "2026-03")
        self.assertAlmostEqual(b["net_social"] + b["total_salarial"], 3000, places=2)
        self.assertGreater(payroll._reduction_generale(payroll.params(2026), 1823.03, 151.67, 1), 0)
        payroll.pay_salaries(c, e, "2026-03", "2026-03-31")
        self.assertEqual(ledger.solde(c, e, "421"), 0)

    def test_liasse_balanced(self):
        from compta import liasse
        c = db.connect(":memory:"); demo.load(c); bank.validate_confident(c, 1, 0)
        L = liasse.compute(c, 1, 2026, {"Amendes": 100})
        self.assertTrue(L["equilibre"])
        self.assertEqual(L["resultat_fiscal"]["370 Résultat fiscal — bénéfice"], L["resultat_fiscal"]["resultat_comptable"] + 100)

    def test_foncier_deficit(self):
        from compta import foncier
        r = foncier.compute([{"loyers": 9600, "travaux": 15000, "interets": 2000, "taxe_fonciere": 900}])
        self.assertEqual(r["deficit_revenu_global"], 8320)   # 9600-2000=7600 ; charges 15920 → déficit 8320
        r = foncier.compute([{"loyers": 1000, "interets": 3000, "travaux": 20000}])
        self.assertEqual(r["deficit_revenu_global"], 10700)  # plafond
        self.assertEqual(r["deficit_reportable"], 2000 + (20020 - 10700))

    def test_quote_reminder_expense(self):
        from compta import sales, expenses
        c = db.connect(":memory:"); demo.load(c)
        q = c.execute("SELECT id FROM quotes").fetchone()[0]
        inv = sales.quote_to_invoice(c, 1, q, "2026-03-01")
        with self.assertRaises(ledger.LedgerError):
            sales.quote_to_invoice(c, 1, q)
        r = sales.send_reminder(c, 1, inv, today="2026-05-15")
        self.assertEqual((r["sent"], r["level"]), (False, 1))
        self.assertIn("40 €", sales.LEVELS[3][2])
        self.assertEqual(expenses.km_allowance(100, 5), 63.6)
        x = expenses.create(c, 1, "2026-03-03", "V", "Train", "transport", ttc=50)
        expenses.validate(c, 1, x)
        self.assertEqual(ledger.solde(c, 1, "44566", "2026-03-03", "2026-03-03"), 0)

    def test_exports(self):
        from compta import exports
        c = db.connect(":memory:"); demo.load(c)
        for k in ("resultat", "bilan", "balance", "journal", "factures", "liasse", "paie"):
            self.assertTrue(exports.report_pdf(c, 1, k, 2026).startswith(b"%PDF"))
            self.assertTrue(exports.report_xlsx(c, 1, k, 2026).startswith(b"PK"))

    def test_pdf_builtin_extractor(self):
        from compta import documents
        data = open(os.path.join(os.path.dirname(__file__), "facture_test.pdf"), "rb").read()
        self.assertIn("Total TTC : 300,00", documents.pdf_text_builtin(data))

    def test_auth_passwords(self):
        from compta import auth
        auth.ITER = 1000
        c = db.connect(":memory:")
        auth.setup(c, "a@b.fr", "A", "motdepasse1")
        with self.assertRaises(auth.AuthError):
            auth.login(c, "a@b.fr", "faux")
        tok, u = auth.login(c, "a@b.fr", "motdepasse1")
        self.assertEqual(auth.user_from_token(c, tok)["email"], "a@b.fr")
        self.assertNotIn(tok, str(c.execute("SELECT token FROM sessions").fetchall()))  # seule l'empreinte est stockée
        with self.assertRaises(ledger.LedgerError):
            auth.create_user(c, "x@y.fr", "x", "court")

class Taxes(unittest.TestCase):
    def test_ir_single(self):
        r = tax.impot_revenu({"salaires": 33334}, 2025)
        self.assertEqual(r["revenu_net_imposable"], 30001)
        self.assertEqual(r["impot_brut"], 2104)   # (29579-11600)*11% + (30001-29579)*30%

    def test_ir_family_and_credits(self):
        r = tax.impot_revenu({"salaires": 60000, "situation": "marie", "enfants": 2, "dons": 500, "emploi_domicile": 3000}, 2025)
        self.assertEqual(r["parts"], 3)
        self.assertEqual(r["impot_bareme"], 2112)
        self.assertEqual(r["decote"], 527)
        self.assertEqual(r["credits"], 1500)

    def test_qf_cap(self):
        r = tax.impot_revenu({"salaires": 300000, "situation": "celibataire", "enfants": 3}, 2025)
        self.assertGreater(r["plafonnement_qf"], 0)

    def test_is(self):
        self.assertEqual(tax.impot_societes(100000)["is"], round(42500 * .15 + 57500 * .25))
        self.assertEqual(tax.impot_societes(-10)["is"], 0)

    def test_ir_from_ledger(self):
        c = db.connect(":memory:")
        demo.load(c)
        p = business.prepare_ir(c, 2, 2026)
        self.assertEqual(p["donnees"]["salaires"], 5900)
        self.assertEqual(p["donnees"]["garde_enfants"], 420)

    def test_filing_without_edi(self):
        c, e = new()
        out = filing.save_and_submit(c, e, "tva", "2026-01", {"a_payer": 10, "credit": 0}, submit=True)
        self.assertEqual(out["status"], "prete")
        self.assertIn("Dépôt automatique indisponible", out["depot"])

if __name__ == "__main__":
    unittest.main()

class Expert(unittest.TestCase):
    """Comptabilité détaillée, profil IA, Agent Impôts, obligations et agents."""
    def setUp(self):
        self.c = db.connect(":memory:"); demo.load(self.c)

    def test_tiers_lettrage_fec(self):
        c = self.c
        acc = c.execute("SELECT account FROM tiers WHERE nom='ACME SA'").fetchone()[0]
        self.assertTrue(acc.startswith("411"))
        bank.validate_confident(c, 1, 0)
        self.assertTrue(all(l["lettrage"] for l in tiers.open_lines(c, 1, acc)))
        fec = ledger.fec(c, 1, 2026)
        self.assertIn("\t411\tClients\t" + acc, fec)

    def test_international_vat(self):
        c = self.c
        with self.assertRaises(ledger.LedgerError):
            business.create_invoice(c, 1, "sale", "Sans numéro", "2026-05-02", [{"label": "x", "qty": 1, "unit_price": 100}], operation="ue_services")
        business.create_invoice(c, 1, "purchase", "AWS EMEA", "2026-05-03", [{"label": "Cloud", "qty": 1, "unit_price": 100}], operation="ue_services")
        d = tax.ca3(c, 1, "2026-05-01", "2026-05-31")
        self.assertEqual(d["collectee"], 20.0); self.assertEqual(d["deductible"], 20.0); self.assertEqual(d["a_payer"], 0)

    def test_closing_cycle_balanced(self):
        from compta import closing, liasse
        c = self.c
        bank.validate_confident(c, 1, 0)
        closing.regularisation(c, 1, "cca", "616", 40, 2026, "Assurance")
        closing.regularisation(c, 1, "fnp", "622", 300, 2026, "Honoraires", tva_rate=20)
        business.close_year(c, 1, 2026)
        closing.allocate_result(c, 1, 2026, "2027-06-30", dividendes=200)
        for y in (2026, 2027):
            self.assertTrue(ledger.balance_sheet(c, 1, f"{y}-12-31")["equilibre"])
            self.assertTrue(liasse.compute(c, 1, y)["equilibre"])
        self.assertEqual(ledger.solde(c, 1, "6", "2026-01-01", "2026-12-31"), 0)  # comptes de gestion soldés

    def test_reconciliation_and_reverse(self):
        from compta import closing
        c = self.c
        bank.validate_confident(c, 1, 0)
        r = closing.reconciliation(c, 1, "2026-12-31", 3250.63 + 2400)
        self.assertTrue(r["equilibre"])  # seul l'achat du MacBook (hors relevé) reste non pointé
        en = ledger.search(c, 1, q="URSSAF")[0]["id"]
        closing.reverse_entry(c, 1, en, "2026-06-30")
        with self.assertRaises(ledger.LedgerError):
            closing.reverse_entry(c, 1, en, "2026-06-30")

    def test_analysis(self):
        from compta import analysis
        bank.validate_confident(self.c, 1, 0)
        s = analysis.sig(self.c, 1, 2026)
        net = next(l["montant"] for l in s["lignes"] if l["libelle"] == "= Résultat net")
        self.assertEqual(net, ledger.euros(ledger.income_statement(self.c, 1, "2026-01-01", "2026-12-31")["resultat"]))
        self.assertEqual(len(analysis.cash_forecast(self.c, 1, 6)["mois"]), 6)

    def test_profile_interview(self):
        from compta import profile
        c = self.c
        e = c.execute("INSERT INTO entities(name,kind) VALUES('F','particulier')").lastrowid
        r = profile.answer(c, e, "particulier", "prenom", free_text="Je m'appelle Léa, pacsée, deux enfants nés en 2017 et 2020, salariée, locataire à Paris")
        p, _ = profile.get(c, e)
        self.assertEqual((p["prenom"], p["situation"], p["enfants"], p["activite"], p["departement"]), ("Léa", "pacse", 2, "salarie", "75"))
        self.assertEqual(r["question"]["id"], "naissance")

    def test_tax_agent(self):
        from compta import tax_agent, exports
        c = self.c
        pdf = exports.PDF("x"); pdf.para("BULLETIN DE SALAIRE décembre 2026"); pdf.para("Net imposable cumulé : 43 812,55")
        tax_agent.add_document(c, 2, 2026, "bulletin.pdf", "application/pdf", pdf.output())
        d = tax_agent.build(c, 2, 2026)
        self.assertEqual(d["parts"], 3.0)
        self.assertEqual(d["donnees"]["salaires"]["valeur"], 43812.55)
        self.assertTrue(any(o["titre"].startswith("Frais réels") and o["gain"] > 0 for o in d["optimisations"]))
        self.assertIn("2042-C-PRO", d["calcul"]["formulaires"])
        self.assertEqual(d["donnees"]["garde_enfants"]["valeur"], 3200)   # comptabilité partielle ≠ estimation annuelle
        out = tax_agent.submit(c, 2, 2026, d)
        self.assertTrue(out["copilote"]["cases"])

    def test_obligations_and_agents(self):
        from compta import obligations, agents
        c = self.c
        done = obligations.run(c, 1, 2026)
        self.assertTrue(done and all(x["statut"] == "simulee" for x in done))
        for name in agents.AGENTS:
            r = agents.run(c, 1 if name != "impots" else 2, name, 2026)
            self.assertFalse(any(i["titre"] == "Analyse indisponible" for i in r["analyses"]), name)
        self.assertIn("autoliquidation", agents.ask(c, 1, "tva", 2026, "client belge ?")["answer"].lower())
