"""TVA : CA3 stable après liquidation, liquidation de tous les comptes de TVA, TVA sur immobilisations, lignes de taux."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COMPTA_NO_DOTENV"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("COMPTA_AI_PROXY", None)
from compta import db, ledger, tax, vat, business
import demo

START, END = "2026-06-01", "2026-06-30"

class _Base(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(os.path.join(tempfile.mkdtemp(), "tva.db"))
        demo.load(self.con)
        self.eid = self.con.execute("SELECT id FROM entities WHERE kind='entreprise'").fetchone()[0]

    def tearDown(self):
        self.con.close()

    def _sale(self, ht=100000, rate=20.0, date="2026-06-10"):
        tva = round(ht * rate / 100)
        ledger.post_entry(self.con, self.eid, date, "VE", f"Vente {rate}",
                          [{"account": "512", "debit": ht + tva}, {"account": "706", "credit": ht},
                           {"account": "44571", "credit": tva, "rate": rate, "base": ht}], source="manual")

    def _purchase(self, ht=50000, rate=20.0, date="2026-06-11"):
        tva = round(ht * rate / 100)
        ledger.post_entry(self.con, self.eid, date, "AC", "Achat",
                          [{"account": "606", "debit": ht}, {"account": "44566", "debit": tva, "rate": rate, "base": ht},
                           {"account": "512", "credit": ht + tva}], source="manual")

    def _autoliquidation(self, ht=100000, date="2026-06-12"):
        tva = round(ht * .2)
        ledger.post_entry(self.con, self.eid, date, "AC", "Prestation UE",
                          [{"account": "622", "debit": ht}, {"account": "445662", "debit": tva, "rate": 20.0, "base": ht},
                           {"account": "4452", "credit": tva, "rate": 20.0, "base": ht}, {"account": "401", "credit": ht}], source="manual")

    def _balance(self, acc):
        return self.con.execute("""SELECT COALESCE(SUM(l.credit - l.debit),0) FROM lines l JOIN entries e ON e.id=l.entry_id
            WHERE e.entity_id=? AND l.account=? AND e.date BETWEEN ? AND ?""", (self.eid, acc, START, END)).fetchone()[0]

class SettlementTests(_Base):
    def test_ca3_is_unchanged_after_the_settlement_entry(self):
        self._sale(); self._purchase()
        before = tax.ca3(self.con, self.eid, START, END)
        self.assertEqual((before["collectee"], before["deductible"], before["a_payer"]), (200.0, 100.0, 100.0))
        tax.post_tva_settlement(self.con, self.eid, START, END)
        after = tax.ca3(self.con, self.eid, START, END)
        self.assertEqual((after["collectee"], after["deductible"], after["a_payer"]), (200.0, 100.0, 100.0))
        self.assertEqual(self._balance("44551"), 10000)          # TVA à décaisser : 100 €

    def test_settlement_clears_every_vat_account(self):
        self._sale(); self._purchase(); self._autoliquidation()
        business.add_asset(self.con, self.eid, "Ordinateur", "2026-06-13", 1000, 3, tva_rate=20)
        tax.post_tva_settlement(self.con, self.eid, START, END)
        for acc in ("44571", "4452", "44566", "445662", "44562"):
            self.assertEqual(self._balance(acc), 0, f"{acc} doit être soldé")
        # collectée 200 + 200 ; déductible 100 + 200 + 200 : crédit de TVA de 100 €
        self.assertEqual(self._balance("44567"), -10000)

    def test_second_settlement_for_the_same_period_is_refused(self):
        self._sale()
        tax.post_tva_settlement(self.con, self.eid, START, END)
        with self.assertRaises(ledger.LedgerError):
            tax.post_tva_settlement(self.con, self.eid, START, END)

    def test_international_lines_ignore_the_settlement(self):
        self._autoliquidation()
        before = vat.international_lines(self.con, self.eid, START, END)
        tax.post_tva_settlement(self.con, self.eid, START, END)
        self.assertEqual(vat.international_lines(self.con, self.eid, START, END), before)

class CounterpartTests(_Base):
    def test_encaissement_and_acompte_entries_still_count_but_not_the_settlement(self):
        """Seule la liquidation est ignorée : la bascule à l'encaissement (source tva) reste dans la CA3."""
        ledger.post_entry(self.con, self.eid, "2026-06-20", "OD", "TVA exigible à l'encaissement — FA-TEST",
                          [{"account": "44574", "debit": 20000}, {"account": "44571", "credit": 20000, "rate": 20.0, "base": 100000}], source="tva")
        self.assertEqual(tax.ca3(self.con, self.eid, START, END)["collectee"], 200.0)
        ledger.post_entry(self.con, self.eid, "2026-06-30", "OD", "Liquidation TVA 2026-06-01 → 2026-06-30 (ancienne)",
                          [{"account": "44571", "debit": 20000}, {"account": "44551", "credit": 20000}], source="tva")
        self.assertEqual(tax.ca3(self.con, self.eid, START, END)["collectee"], 200.0)

class AssetVatTests(_Base):
    def _entry_lines(self, label):
        en = self.con.execute("SELECT id FROM entries WHERE entity_id=? AND source='asset' AND label=?", (self.eid, label)).fetchone()[0]
        return {l["account"]: (l["debit"], l["credit"]) for l in self.con.execute("SELECT account, debit, credit FROM lines WHERE entry_id=?", (en,))}

    def test_deductible_vat_goes_to_44562_and_cost_stays_ht(self):
        business.add_asset(self.con, self.eid, "Ordinateur", "2026-06-13", 1000, 3, tva_rate=20)
        lines = self._entry_lines("Acquisition immobilisation : Ordinateur")
        self.assertEqual(lines["2183"], (100000, 0))
        self.assertEqual(lines["44562"], (20000, 0))
        self.assertEqual(lines["512"], (0, 120000))
        self.assertEqual(self.con.execute("SELECT cost FROM assets WHERE label='Ordinateur'").fetchone()[0], 100000)

    def test_no_vat_without_rate_or_in_franchise(self):
        business.add_asset(self.con, self.eid, "Sans TVA", "2026-06-13", 1000, 3)
        self.assertNotIn("44562", self._entry_lines("Acquisition immobilisation : Sans TVA"))
        self.con.execute("UPDATE entities SET tva_regime='franchise' WHERE id=?", (self.eid,))
        business.add_asset(self.con, self.eid, "Franchise", "2026-06-14", 1000, 3, tva_rate=20)
        lines = self._entry_lines("Acquisition immobilisation : Franchise")
        self.assertNotIn("44562", lines)
        self.assertEqual(lines["512"], (0, 100000))

class RateLinesTests(_Base):
    def test_reduced_rate_21_is_listed(self):
        self._sale(rate=2.1)
        lignes = tax.ca3(self.con, self.eid, START, END)["lignes"]
        self.assertAlmostEqual(lignes["Taux 2,1 % — TVA"], 21.0)
        self.assertNotIn("Autres taux — TVA", lignes)

    def test_unlisted_rate_appears_as_other_rate_so_lines_add_up(self):
        self._sale(rate=8.5)
        lignes = tax.ca3(self.con, self.eid, START, END)["lignes"]
        self.assertAlmostEqual(lignes["Autres taux — TVA"], 85.0)

if __name__ == "__main__":
    unittest.main()
