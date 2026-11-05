"""Tests de bout en bout du serveur HTTP : authentification, rôles, exports."""
import json, os, sys, tempfile, threading, unittest, urllib.request, urllib.error, base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COMPTA_NO_DOTENV"] = "1"  # un .env local ne doit pas réactiver l'IA pendant les tests
os.environ.pop("ANTHROPIC_API_KEY", None)
import server, demo
from compta import db, auth
from http.server import ThreadingHTTPServer

class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth.ITER = 1000  # accélère les tests
        cls.tmp = tempfile.mkdtemp()
        server.CON = db.connect(os.path.join(cls.tmp, "t.db"))
        demo.load(server.CON)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, body=None, cookie=None, entity=1, ctype="application/json", raw=False):
        h = {"X-Entity": str(entity)}
        if cookie:
            h["Cookie"] = f"session={cookie}"
        if body is not None:
            h["Content-Type"] = ctype
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                return r.status, (data if raw else json.loads(data)), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers

    def login(self, email, pwd="demo-compta"):
        code, _, h = self.call("/api/auth/login", {"email": email, "password": pwd})
        self.assertEqual(code, 200)
        return h["Set-Cookie"].split("session=")[1].split(";")[0]

    def test_auth_required_and_bad_password(self):
        self.assertEqual(self.call("/api/dashboard")[0], 401)
        self.assertEqual(self.call("/api/auth/login", {"email": "demo@comptaia.fr", "password": "nope"})[0], 403)

    def test_owner_sees_both_entities_comptable_one(self):
        o, cpt = self.login("demo@comptaia.fr"), self.login("comptable@cabinet.fr")
        self.assertEqual(len(self.call("/api/entities", cookie=o)[1]), 2)
        ents = self.call("/api/entities", cookie=cpt)[1]
        self.assertEqual([e["id"] for e in ents], [1])
        self.assertEqual(self.call("/api/dashboard?year=2026", cookie=cpt, entity=2)[0], 403)  # dossier du foyer : interdit
        self.assertEqual(self.call("/api/dashboard?year=2026", cookie=cpt, entity=1)[0], 200)

    def test_roles(self):
        o, cpt = self.login("demo@comptaia.fr"), self.login("comptable@cabinet.fr")
        code, r, _ = self.call("/api/members", {"email": "lecteur@banque.fr", "role": "lecteur"}, cookie=o)
        self.assertEqual(code, 200)
        self.assertTrue(r["mot_de_passe_provisoire"])
        lec = self.login("lecteur@banque.fr", r["mot_de_passe_provisoire"])
        self.assertEqual(self.call("/api/reports/bilan?year=2026", cookie=lec)[0], 200)
        self.assertEqual(self.call("/api/bank/validate-confident", {}, cookie=lec)[0], 403)
        self.assertEqual(self.call("/api/members", {"email": "x@y.fr", "role": "lecteur"}, cookie=cpt)[0], 403)
        self.assertEqual(self.call("/api/bank/validate-confident", {}, cookie=cpt)[0], 200)
        log = self.call("/api/audit-log", cookie=o)[1]
        self.assertTrue(any(l["email"] == "comptable@cabinet.fr" for l in log))

    def test_csrf_content_type(self):
        o = self.login("demo@comptaia.fr")
        self.assertEqual(self.call("/api/bank/validate-confident", {}, cookie=o, ctype="text/plain")[0], 415)

    def test_downloads(self):
        o = self.login("demo@comptaia.fr")
        code, data, h = self.call("/api/export/pdf/bilan?year=2026", cookie=o, raw=True)
        self.assertEqual(code, 200); self.assertTrue(data.startswith(b"%PDF"))
        code, data, h = self.call("/api/export/xlsx/liasse?year=2026", cookie=o, raw=True)
        self.assertTrue(data.startswith(b"PK")); self.assertIn("attachment", h["Content-Disposition"])
        code, data, _ = self.call("/api/payslips/1/pdf", cookie=o, raw=True)
        self.assertTrue(data.startswith(b"%PDF"))
        code, data, _ = self.call("/api/dsn?period=2026-01&download=1", cookie=o, raw=True)
        self.assertIn(b"S21.G00.30.002,'Durand'", data)

    def test_document_upload(self):
        o = self.login("demo@comptaia.fr")
        pdf = open(os.path.join(os.path.dirname(__file__), "facture_test.pdf"), "rb").read()
        code, r, _ = self.call("/api/documents/read", {"data": base64.b64encode(pdf).decode(), "mime": "application/pdf"}, cookie=o)
        self.assertEqual(code, 200)
        self.assertEqual(r["number"], "F-2026-118")
        self.assertEqual(r["lines"][0]["unit_price"], 250.0)

    def test_edi_sandbox_tva(self):
        o = self.login("demo@comptaia.fr")
        ca3 = self.call("/api/tax/ca3?start=2026-01-01&end=2026-01-31", cookie=o)[1]
        code, r, _ = self.call("/api/declarations", {"type": "tva", "period": "2026-01", "data": ca3, "submit": True}, cookie=o)
        self.assertEqual(r["status"], "simulee")
        self.assertTrue(self.call("/api/edi/submissions", cookie=o)[1][0]["ref"].startswith("SBX-TVA"))

if __name__ == "__main__":
    unittest.main()
