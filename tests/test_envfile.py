"""Tests du chargement de `.env` : analyse, non-écrasement de l'environnement, garde des tests."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from compta import envfile

class ParseTests(unittest.TestCase):
    def test_parse_forms(self):
        text = ("# commentaire\n\nANTHROPIC_API_KEY=sk-test-123\n"
                'export COMPTA_MODEL="claude-opus-5-5"\n'
                "QUOTED='valeur avec espaces'\n"
                "PORT=9000  # commentaire en fin de ligne\n"
                "ligne sans egal\n"
                "bad-name=ignore\n")
        self.assertEqual(envfile.parse(text), {
            "ANTHROPIC_API_KEY": "sk-test-123", "COMPTA_MODEL": "claude-opus-5-5",
            "QUOTED": "valeur avec espaces", "PORT": "9000"})

class LoadTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, ".env")
        for k in ("ENVFILE_TEST_A", "ENVFILE_TEST_B", "COMPTA_NO_DOTENV"):
            os.environ.pop(k, None)
        envfile.LOADED.clear()

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.saved)
        envfile.LOADED.clear()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_loads_and_reports_names_only(self):
        self.write("ENVFILE_TEST_A=secret-value\n")
        self.assertEqual(envfile.load(self.path), ["ENVFILE_TEST_A"])
        self.assertEqual(os.environ["ENVFILE_TEST_A"], "secret-value")
        self.assertEqual(envfile.LOADED, ["ENVFILE_TEST_A"])  # noms, pas valeurs

    def test_never_overrides_existing_environment(self):
        os.environ["ENVFILE_TEST_A"] = "from-env"
        self.write("ENVFILE_TEST_A=from-file\nENVFILE_TEST_B=b\n")
        self.assertEqual(envfile.load(self.path), ["ENVFILE_TEST_B"])
        self.assertEqual(os.environ["ENVFILE_TEST_A"], "from-env")

    def test_disabled_by_guard(self):
        os.environ["COMPTA_NO_DOTENV"] = "1"
        self.write("ENVFILE_TEST_A=x\n")
        self.assertEqual(envfile.load(self.path), [])
        self.assertNotIn("ENVFILE_TEST_A", os.environ)

    def test_missing_file_is_noop(self):
        self.assertEqual(envfile.load(os.path.join(self.tmp, "absent.env")), [])

if __name__ == "__main__":
    unittest.main()
