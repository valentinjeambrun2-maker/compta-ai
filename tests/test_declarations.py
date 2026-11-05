"""Déclarations : une déclaration déposée n'est jamais rouverte, brouillon unique, contrôles de cohérence, accusés EDI."""
import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COMPTA_NO_DOTENV"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("COMPTA_AI_PROXY", None)
from compta import db, ledger, tax, filing, edi, obligations
import demo

class _Base(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(os.path.join(tempfile.mkdtemp(), "decl.db"))
        demo.load(self.con)
        self.eid = self.con.execute("SELECT id FROM entities WHERE kind='entreprise'").fetchone()[0]

    def tearDown(self):
        self.con.close()

    def _ca3(self, start="2026-01-01", end="2026-01-31"):
        return json.loads(json.dumps(tax.ca3(self.con, self.eid, start, end), default=str))

    def _count(self, typ="tva", period="2026-01"):
        return self.con.execute("SELECT COUNT(*) FROM declarations WHERE entity_id=? AND type=? AND period=?", (self.eid, typ, period)).fetchone()[0]

    def _statut(self, typ="tva", period="2026-01"):
        return next(o for o in obligations.listing(self.con, self.eid, 2026)["obligations"] if o["type"] == typ and o["periode"] == period)["statut"]

class FiledDeclarationTests(_Base):
    def test_viewing_a_filed_declaration_does_not_reopen_it(self):
        r1 = filing.save_and_submit(self.con, self.eid, "tva", "2026-01", self._ca3())
        self.assertEqual(r1["status"], "prete")
        filing.mark_filed(self.con, self.eid, r1["id"])
        r2 = filing.save_and_submit(self.con, self.eid, "tva", "2026-01", self._ca3())      # « Voir »
        self.assertEqual(r2["status"], "deposee")
        self.assertTrue(r2["deja_depose"])
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._statut(), "deposee")

    def test_a_filed_declaration_cannot_be_submitted_again(self):
        r = filing.save_and_submit(self.con, self.eid, "tva", "2026-01", self._ca3())
        filing.mark_filed(self.con, self.eid, r["id"])
        with self.assertRaises(ledger.LedgerError):
            filing.save_and_submit(self.con, self.eid, "tva", "2026-01", self._ca3(), submit=True)

    def test_draft_is_updated_in_place(self):
        d = self._ca3()
        filing.save_and_submit(self.con, self.eid, "tva", "2026-01", d)
        filing.save_and_submit(self.con, self.eid, "tva", "2026-01", {**d, "note": "version 2"})
        self.assertEqual(self._count(), 1)
        stored = self.con.execute("SELECT data FROM declarations WHERE entity_id=? AND type='tva'", (self.eid,)).fetchone()[0]
        self.assertIn("version 2", stored)

    def test_deposited_row_wins_over_a_newer_draft_in_older_databases(self):
        for st in ("deposee", "prete"):      # ancien comportement : « Voir » ajoutait une ligne « prête » après le dépôt
            self.con.execute("INSERT INTO declarations(entity_id,type,period,data,status) VALUES(?,?,?,?,?)", (self.eid, "tva", "2026-02", "{}", st))
        self.assertEqual(self._statut(period="2026-02"), "deposee")
        self.assertTrue(filing.save_and_submit(self.con, self.eid, "tva", "2026-02", self._ca3("2026-02-01", "2026-02-28"))["deja_depose"])

class ValidationTests(_Base):
    def test_inconsistent_net_vat_is_an_error(self):
        self.assertTrue(filing.validate_decl("tva", {"collectee": 200, "deductible": 100, "a_payer": 50, "credit": 0}))

    def test_consistent_vat_has_no_error(self):
        self.assertEqual(filing.validate_decl("tva", {"collectee": 200, "deductible": 100, "a_payer": 100, "credit": 0}), [])
        self.assertEqual(filing.validate_decl("tva", {"collectee": 100, "deductible": 200, "a_payer": 0, "credit": 100}), [])

    def test_unbalanced_liasse_is_blocked(self):
        self.assertTrue(filing.validate_decl("liasse", {"equilibre": False}))
        self.assertEqual(filing.validate_decl("liasse", {"equilibre": True}), [])

    def test_saving_an_inconsistent_declaration_marks_it_in_error(self):
        r = filing.save_and_submit(self.con, self.eid, "tva", "2026-03", {"collectee": 200, "deductible": 100, "a_payer": 50, "credit": 0})
        self.assertEqual(r["status"], "erreurs")
        self.assertTrue(r["erreurs"])

class AcknowledgementTests(_Base):
    def _submission(self, mode):
        r = filing.save_and_submit(self.con, self.eid, "tva", "2026-01", self._ca3())
        self.con.execute("UPDATE declarations SET status='transmise' WHERE id=?", (r["id"],))
        sub = self.con.execute("INSERT INTO edi_submissions(entity_id,declaration_id,type,mode,ref,status,response) VALUES(?,?,?,?,?,?,?)",
                               (self.eid, r["id"], "tva", mode, "REF1", "recu", "{}")).lastrowid
        return r["id"], sub

    def _refresh(self, sub, partner_status):
        class Partner:
            def status(self, ref):
                return {"ref": ref, "status": partner_status}
        with mock.patch.object(edi, "connector", lambda cfg: Partner()):
            edi.refresh(self.con, self.eid, sub)

    def _declaration_status(self, did):
        return self.con.execute("SELECT status FROM declarations WHERE id=?", (did,)).fetchone()[0]

    def test_accepted_acknowledgement_marks_the_declaration_filed(self):
        did, sub = self._submission("http")
        self._refresh(sub, "accepte")
        self.assertEqual(self._declaration_status(did), "deposee")

    def test_sandbox_acceptance_is_only_simulated(self):
        did, sub = self._submission("sandbox")
        self._refresh(sub, "accepte")
        self.assertEqual(self._declaration_status(did), "simulee")

    def test_rejection_marks_the_declaration_in_error(self):
        did, sub = self._submission("http")
        self._refresh(sub, "rejete")
        self.assertEqual(self._declaration_status(did), "erreurs")

if __name__ == "__main__":
    unittest.main()
