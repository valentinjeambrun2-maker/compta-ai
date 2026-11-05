import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("ANTHROPIC_API_KEY", None)
from compta import db, pcg, ledger, bank, tax, business, filing
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
        self.assertEqual(ledger.solde(c, e, "625"), 10000)
        self.assertEqual(ledger.solde(c, e, "44566"), 2000)

    def test_bank_lettrage(self):
        c = db.connect(":memory:")
        demo.load(c)
        tx = c.execute("SELECT * FROM bank_tx WHERE label LIKE '%ACME%'").fetchone()
        self.assertEqual(tx["account"], "411")
        bank.validate(c, 1, tx["id"])
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
