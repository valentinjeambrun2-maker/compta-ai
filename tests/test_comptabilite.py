"""Comptabilité : annulation par contre-passation (sans suppression) et pagination du journal et de la recherche."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COMPTA_NO_DOTENV"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("COMPTA_AI_PROXY", None)
from compta import db, ledger, bank
import demo

class _Base(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(os.path.join(tempfile.mkdtemp(), "compta.db"))
        demo.load(self.con)
        self.eid = self.con.execute("SELECT id FROM entities WHERE kind='entreprise'").fetchone()[0]

    def tearDown(self):
        self.con.close()

    def _entry(self, label="Achat test", amount=12345, date="2026-06-05"):
        return ledger.post_entry(self.con, self.eid, date, "OD", label,
                                 [{"account": "606", "debit": amount}, {"account": "512", "credit": amount}], source="manual")

    def _net(self, entry_ids, account):
        marks = ",".join("?" * len(entry_ids))
        return self.con.execute(f"SELECT COALESCE(SUM(debit-credit),0) FROM lines WHERE account=? AND entry_id IN ({marks})",
                                [account, *entry_ids]).fetchone()[0]

class CancelTests(_Base):
    def test_cancel_keeps_original_and_nets_to_zero(self):
        en = self._entry()
        nid = ledger.cancel_entry(self.con, self.eid, en, day="2026-06-06")
        self.assertIsNotNone(self.con.execute("SELECT id FROM entries WHERE id=?", (en,)).fetchone())   # rien n'est effacé
        self.assertEqual(self.con.execute("SELECT reversal_of FROM entries WHERE id=?", (nid,)).fetchone()[0], en)
        self.assertEqual(self.con.execute("SELECT source FROM entries WHERE id=?", (nid,)).fetchone()[0], "annulation")
        self.assertEqual(self._net([en, nid], "606"), 0)
        self.assertEqual(self._net([en, nid], "512"), 0)

    def test_cancelled_entry_is_marked_and_not_cancellable_twice(self):
        en = self._entry()
        ledger.cancel_entry(self.con, self.eid, en, day="2026-06-06")
        row = next(r for r in ledger.journal(self.con, self.eid, "2026-06-01", "2026-06-30") if r["id"] == en)
        self.assertIsNotNone(row["reversed_by"])
        with self.assertRaises(ledger.LedgerError):
            ledger.cancel_entry(self.con, self.eid, en, day="2026-06-06")

    def test_bank_line_goes_back_to_pending(self):
        bank.import_rows(self.con, self.eid, [{"date": "2026-06-08", "label": "CB ANNULATION TEST", "amount": -4500}])
        tx = self.con.execute("SELECT id FROM bank_tx WHERE label='CB ANNULATION TEST'").fetchone()[0]
        bank.validate(self.con, self.eid, tx, "606", 0)
        en = self.con.execute("SELECT entry_id FROM bank_tx WHERE id=?", (tx,)).fetchone()[0]
        ledger.cancel_entry(self.con, self.eid, en, day="2026-06-09")
        row = self.con.execute("SELECT status, entry_id FROM bank_tx WHERE id=?", (tx,)).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["entry_id"])

    def test_lettered_entry_is_refused(self):
        en = self._entry()
        self.con.execute("UPDATE lines SET lettrage='LTEST' WHERE entry_id=? AND account='512'", (en,))
        with self.assertRaises(ledger.LedgerError):
            ledger.cancel_entry(self.con, self.eid, en, day="2026-06-06")

    def test_invoice_entry_is_refused(self):
        row = self.con.execute("SELECT entry_id FROM invoices WHERE entity_id=? AND entry_id IS NOT NULL LIMIT 1", (self.eid,)).fetchone()
        self.assertIsNotNone(row, "la démo doit contenir une facture comptabilisée")
        with self.assertRaises(ledger.LedgerError):
            ledger.cancel_entry(self.con, self.eid, row[0], day="2026-06-06")

    def test_journal_flags_invoice_and_lettered_entries(self):
        inv = self.con.execute("SELECT entry_id FROM invoices WHERE entity_id=? AND entry_id IS NOT NULL LIMIT 1", (self.eid,)).fetchone()[0]
        rows = {r["id"]: r for r in ledger.journal(self.con, self.eid, "2026-01-01", "2026-12-31", limit=None)}
        self.assertGreaterEqual(rows[inv]["facture"], 1)
        en = self._entry(date="2026-06-12")
        self.con.execute("UPDATE lines SET lettrage='LFLAG' WHERE entry_id=? AND account='512'", (en,))
        rows = {r["id"]: r for r in ledger.journal(self.con, self.eid, "2026-06-01", "2026-06-30", limit=None)}
        self.assertGreaterEqual(rows[en]["lettree"], 1)

    def test_closed_period_is_refused(self):
        en = self._entry(date="2026-03-10")
        self.con.execute("UPDATE entities SET closed_until='2026-03-31' WHERE id=?", (self.eid,))
        with self.assertRaises(ledger.LedgerError):
            ledger.cancel_entry(self.con, self.eid, en, day="2026-03-15")

class PagingTests(_Base):
    def setUp(self):
        super().setUp()
        for i in range(7):
            self._entry(label=f"Lot test {i}", amount=1000 + i, date=f"2026-06-0{i + 1}")

    def test_journal_pages_do_not_overlap_and_total_is_exact(self):
        total = ledger.journal_total(self.con, self.eid, "2026-06-01", "2026-06-30")
        self.assertEqual(total, 7)
        p1 = ledger.journal(self.con, self.eid, "2026-06-01", "2026-06-30", limit=3, offset=0)
        p2 = ledger.journal(self.con, self.eid, "2026-06-01", "2026-06-30", limit=3, offset=3)
        self.assertEqual(len(p1), 3)
        self.assertEqual(len(p2), 3)
        self.assertTrue({e["id"] for e in p1}.isdisjoint({e["id"] for e in p2}))
        self.assertEqual(len(ledger.journal(self.con, self.eid, "2026-06-01", "2026-06-30", limit=None)), total)

    def test_search_total_counts_every_match(self):
        kw = dict(q="Lot", start="2026-06-01", end="2026-06-30")
        self.assertEqual(ledger.search_total(self.con, self.eid, **kw), 7)
        page = ledger.search(self.con, self.eid, limit=2, offset=0, **kw)
        self.assertEqual(len(page), 2)
        self.assertIn("reversed_by", page[0])

if __name__ == "__main__":
    unittest.main()
