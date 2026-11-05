"""Banque : mémoire des choix (règles par libellé) et détection des doublons avec la comptabilité."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COMPTA_NO_DOTENV"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("COMPTA_AI_PROXY", None)
from compta import db, bank, ledger
import demo

class RuleKeyTests(unittest.TestCase):
    def test_same_merchant_other_dates_share_the_rule(self):
        self.assertEqual(bank.rule_key("CB CARREFOUR MARKET 05/01", -12345), bank.rule_key("CB CARREFOUR MARKET 12/02", -999))

    def test_flow_direction_separates_rules(self):
        self.assertNotEqual(bank.rule_key("VIR ACME", 100), bank.rule_key("VIR ACME", -100))

    def test_accents_and_case_ignored(self):
        self.assertEqual(bank.rule_key("PRLV Électricité", -1), bank.rule_key("PRLV ELECTRICITE", -1))

    def test_noise_only_label_has_no_rule(self):
        self.assertIsNone(bank.rule_key("CB 1234 05/01", -100))

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(os.path.join(tempfile.mkdtemp(), "bank.db"))
        demo.load(self.con)
        self.eid = self.con.execute("SELECT id FROM entities WHERE kind='entreprise'").fetchone()[0]

    def tearDown(self):
        self.con.close()

    def _tx_id(self, label, date):
        return self.con.execute("SELECT id FROM bank_tx WHERE entity_id=? AND label=? AND date=?", (self.eid, label, date)).fetchone()[0]

    def test_explicit_choice_is_reused_on_next_import(self):
        bank.import_rows(self.con, self.eid, [{"date": "2026-06-02", "label": "CB BOULANGERIE TESTA", "amount": -1850}])
        bank.validate(self.con, self.eid, self._tx_id("CB BOULANGERIE TESTA", "2026-06-02"), "606", 5.5)
        res = bank.import_rows(self.con, self.eid, [{"date": "2026-06-20", "label": "CB BOULANGERIE TESTA", "amount": -2390}])
        self.assertEqual(res["rules_applied"], 1)
        row = self.con.execute("SELECT account, confidence, reason FROM bank_tx WHERE entity_id=? AND date='2026-06-20'", (self.eid,)).fetchone()
        self.assertEqual(row["account"], "606")
        self.assertAlmostEqual(row["confidence"], .95)
        self.assertIn("Règle mémorisée", row["reason"])

    def test_validation_without_explicit_account_learns_nothing(self):
        bank.import_rows(self.con, self.eid, [{"date": "2026-06-03", "label": "CB LIBRAIRIE ZETA", "amount": -1500}])
        before = self.con.execute("SELECT COUNT(*) FROM bank_rules WHERE entity_id=?", (self.eid,)).fetchone()[0]
        bank.validate(self.con, self.eid, self._tx_id("CB LIBRAIRIE ZETA", "2026-06-03"))
        after = self.con.execute("SELECT COUNT(*) FROM bank_rules WHERE entity_id=?", (self.eid,)).fetchone()[0]
        self.assertEqual(before, after)

    def test_possible_duplicate_of_manual_entry_is_flagged_not_bulk_validated(self):
        ledger.post_entry(self.con, self.eid, "2026-06-10", "ACH", "Achat saisi à la main",
                          [{"account": "606", "debit": 4217}, {"account": "512", "credit": 4217}], source="manual")
        res = bank.import_rows(self.con, self.eid, [{"date": "2026-06-11", "label": "CB FOURNISSEUR MANUEL", "amount": -4217}])
        self.assertEqual(res["possible_duplicates"], 1)
        row = self.con.execute("SELECT confidence, reason FROM bank_tx WHERE entity_id=? AND label='CB FOURNISSEUR MANUEL'", (self.eid,)).fetchone()
        self.assertLessEqual(row["confidence"], .3)
        self.assertTrue(row["reason"].startswith("Doublon possible"))
        validated = bank.validate_confident(self.con, self.eid, 0.8)["validated"]
        self.assertEqual(self.con.execute("SELECT status FROM bank_tx WHERE entity_id=? AND label='CB FOURNISSEUR MANUEL'", (self.eid,)).fetchone()[0], "pending")
        self.assertIsInstance(validated, int)

if __name__ == "__main__":
    unittest.main()
