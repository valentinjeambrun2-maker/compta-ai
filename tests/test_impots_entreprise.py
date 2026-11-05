"""Impôts & liasse (entreprise) : IS au 444, reclassement d'un IS passé au 44551, SIREN, contrôles, acomptes."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COMPTA_NO_DOTENV"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("COMPTA_AI_PROXY", None)
from compta import db, ledger, business, liasse, obligations
import demo

class _Base(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(os.path.join(tempfile.mkdtemp(), "is.db"))
        demo.load(self.con)
        self.eid = self.con.execute("SELECT id FROM entities WHERE kind='entreprise'").fetchone()[0]
        self.con.execute("UPDATE entities SET siret=? WHERE id=?", ("123 456 789 00012", self.eid))

    def tearDown(self):
        self.con.close()

    def _profit(self, amount=10000000, date="2026-06-15"):
        """Vente de 100 000 € : fait un bénéfice imposable."""
        ledger.post_entry(self.con, self.eid, date, "VE", "Vente test",
                          [{"account": "512", "debit": amount}, {"account": "706", "credit": amount}], source="manual")

    def _closing_is(self, acc, year=2026):
        return self.con.execute("""SELECT COALESCE(SUM(l.credit - l.debit), 0) FROM lines l JOIN entries en ON en.id = l.entry_id
            WHERE en.entity_id=? AND en.source='closing' AND en.label=? AND l.account=?""",
            (self.eid, f"Impôt sur les sociétés {year}", acc)).fetchone()[0]

class IsAt444Tests(_Base):
    def test_close_year_books_is_on_444_not_on_vat(self):
        self._profit()
        business.close_year(self.con, self.eid, 2026)
        is_cents = self._closing_is("444")
        self.assertGreater(is_cents, 0)
        self.assertEqual(self._closing_is("44551"), 0, "l'IS ne doit plus aller au compte de TVA")
        self.assertEqual(self.con.execute("""SELECT COALESCE(SUM(l.debit),0) FROM lines l JOIN entries en ON en.id=l.entry_id
            WHERE en.entity_id=? AND en.source='closing' AND en.label=? AND l.account='695'""",
            (self.eid, "Impôt sur les sociétés 2026")).fetchone()[0], is_cents)

class ReclassementTests(_Base):
    def _legacy(self):
        """Ancien comportement : IS 2025 passé au 44551."""
        ledger.post_entry(self.con, self.eid, "2025-12-31", "OD", "Impôt sur les sociétés 2025",
                          [{"account": "695", "debit": 50000}, {"account": "44551", "credit": 50000}], source="closing")

    def test_reclassement_moves_balance_and_is_idempotent(self):
        self._legacy()
        r = business.corriger_is(self.con, self.eid, 2025)
        self.assertEqual(r["montant_eur"], 500)
        self.assertFalse(r["deja_fait"])
        net_vat = self.con.execute("""SELECT COALESCE(SUM(l.credit - l.debit),0) FROM lines l JOIN entries en ON en.id=l.entry_id
            WHERE en.entity_id=? AND l.account='44551' AND en.source IN ('closing','correction_is') AND en.label LIKE '%2025%'""",
            (self.eid,)).fetchone()[0]
        self.assertEqual(net_vat, 0)
        r2 = business.corriger_is(self.con, self.eid, 2025)
        self.assertTrue(r2["deja_fait"])

    def test_controls_flag_legacy_until_corrected(self):
        self._legacy()
        acts = [c.get("action") for c in liasse.compute(self.con, self.eid, 2025)["controles"]]
        self.assertIn("corriger_is", acts)
        business.corriger_is(self.con, self.eid, 2025)
        acts = [c.get("action") for c in liasse.compute(self.con, self.eid, 2025)["controles"]]
        self.assertNotIn("corriger_is", acts)

class LiasseTests(_Base):
    def test_siren_is_nine_digits_for_both_siret_formats(self):
        self.assertEqual(liasse.compute(self.con, self.eid, 2026)["2065"]["SIREN"], "123456789")
        self.con.execute("UPDATE entities SET siret=? WHERE id=?", ("12345678900012", self.eid))
        self.assertEqual(liasse.compute(self.con, self.eid, 2026)["2065"]["SIREN"], "123456789")

class AcomptesTests(_Base):
    def test_is_balance_is_net_of_acomptes_paid(self):
        self._profit()
        ledger.post_entry(self.con, self.eid, "2026-09-15", "BQ", "Acompte IS",
                          [{"account": "444", "debit": 300000}, {"account": "512", "credit": 300000}], source="manual")
        business.close_year(self.con, self.eid, 2026)
        du = self._closing_is("444") / 100
        item = next(o for o in obligations.listing(self.con, self.eid, 2026)["obligations"] if o["type"] == "is")
        self.assertAlmostEqual(item["montant"], round(du - 3000, 2), places=2)

if __name__ == "__main__":
    unittest.main()
