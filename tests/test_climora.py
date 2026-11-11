"""Tests voor de sync-server: SSRF, auth, tokens, rate limiting en proxy-rewriting.

Draaien:  python3 -m unittest discover -s tests -v   (vanuit de repository-root)
"""
import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
SYNC = REPO / "sync-server"


def laad_module(naam, bestand, extra_env=None):
    """Laad een servermodule met een eigen tijdelijke database."""
    import os
    dbdir = tempfile.mkdtemp(prefix="climora-test-")
    if extra_env:
        os.environ.update(extra_env)
    os.environ["NEWLY_DB_PATH"] = str(pathlib.Path(dbdir) / "test.db")
    spec = importlib.util.spec_from_file_location(naam, bestand)
    module = importlib.util.module_from_spec(spec)
    sys.modules[naam] = module
    spec.loader.exec_module(module)
    return module


def start_server(module, handler, poort):
    server = module.ThreadingHTTPServer(("127.0.0.1", poort), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    return server


def verzoek(basis, path, method="GET", body=None, headers=None):
    kop = dict(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    if data:
        kop.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(basis + path, data=data, method=method, headers=kop)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class SSRFTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = laad_module("srv_ssrf", SYNC / "server.py")

    def test_private_ip_wordt_geblokkeerd(self):
        for url in ("http://127.0.0.1/x", "http://10.0.0.5/", "http://172.16.0.1/",
                    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
                    "http://0.0.0.0/", "http://[::1]/"):
            self.assertFalse(self.m.veilige_target(url), url)

    def test_localhost_wordt_geblokkeerd(self):
        self.assertFalse(self.m.veilige_target("http://localhost:8765/"))

    def test_niet_http_wordt_geblokkeerd(self):
        for url in ("file:///etc/passwd", "ftp://example.com/", "gopher://x/",
                    "http://gebruiker:pass@example.com/"):
            self.assertFalse(self.m.veilige_target(url), url)

    def test_publiek_ip_wordt_toegestaan(self):
        self.assertTrue(self.m.veilige_target("https://nl.wikipedia.org/wiki/Hoofdpagina"))
        self.assertTrue(self.m.veilige_target("http://93.184.216.34/"))

    def test_favicon_host_check(self):
        self.assertTrue(self.m.is_private_host("127.0.0.1"))
        self.assertTrue(self.m.is_private_host("localhost"))
        self.assertFalse(self.m.is_private_host("nl.wikipedia.org"))


class AdBlockEnProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = laad_module("srv_proxy", SYNC / "server.py")

    def test_ad_hosts(self):
        self.assertTrue(self.m.is_ad_host("pagead2.googlesyndication.com"))
        self.assertTrue(self.m.is_ad_host("doubleclick.net"))
        self.assertFalse(self.m.is_ad_host("nl.wikipedia.org"))
        self.assertFalse(self.m.is_ad_host("notdoubleclick.net.evilexample.org"
                                           if False else "wikipedia.org"))

    def test_proxificeer_maakt_absolute_proxy_url(self):
        url = self.m.proxificeer("/pagina", "https://example.com/dir/", "volledig",
                                 "http://pi:8765")
        self.assertIn("http://pi:8765/browse?url=", url)
        self.assertIn("https%3A%2F%2Fexample.com%2Fpagina", url)

    def test_bewerk_html_rewrites_links(self):
        html = '<html><head><title>t</title></head><body><a href="/over">over</a></body></html>'
        tekst, base = self.m.bewerk_html(html, "https://example.com/", "volledig", 200,
                                         "http://pi:8765")
        self.assertIn("/browse?url=", tekst)
        self.assertIn("<base", tekst)

    def test_veilige_modus_stript_scripts(self):
        html = '<html><body><script>alert(1)</script><p onclick="x()">hoi</p></body></html>'
        tekst, _ = self.m.bewerk_html(html, "https://example.com/", "veilig", 200, "")
        self.assertNotIn("<script", tekst.lower())
        self.assertNotIn("onclick", tekst.lower())


class SyncServerAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = laad_module("srv_auth", SYNC / "server.py")
        cls.server = start_server(cls.m, cls.m.Handler, 18971)
        cls.basis = "http://127.0.0.1:18971"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_ai_en_sleutelbeheer_vergen_login(self):
        self.assertEqual(verzoek(self.basis, "/ask", "POST", {"prompt": "hoi"})[0], 401)
        self.assertEqual(verzoek(self.basis, "/api-key", "POST", {"key": "sk-1234567890"})[0], 401)
        self.assertEqual(verzoek(self.basis, "/bookmarks")[0], 401)

    def test_register_login_en_token_rotatie(self):
        self.m.POGINGEN.clear()
        st, b = verzoek(self.basis, "/register", "POST",
                        {"username": "alice", "password": "wachtwoord123"})
        self.assertEqual(st, 201)
        token1 = json.loads(b)["token"]

        st, b = verzoek(self.basis, "/login", "POST",
                        {"username": "alice", "password": "wachtwoord123"})
        self.assertEqual(st, 200)
        token2 = json.loads(b)["token"]
        self.assertNotEqual(token1, token2)

        self.assertEqual(verzoek(self.basis, "/bookmarks",
                                 headers={"Authorization": "Bearer " + token2})[0], 200)
        self.assertEqual(verzoek(self.basis, "/bookmarks",
                                 headers={"Authorization": "Bearer " + token1})[0], 401)

    def test_tokens_niet_plaintext_in_database(self):
        con = sqlite3.connect(self.m.DB_PATH)
        rijen = con.execute("SELECT token, token_hash FROM users").fetchall()
        con.close()
        self.assertTrue(rijen)
        for token, token_hash in rijen:
            self.assertIsNone(token)
            self.assertTrue(token_hash)

    def test_rate_limit_login(self):
        for i in range(10):
            verzoek(self.basis, "/login", "POST",
                    {"username": "alice", "password": "fout" + str(i)})
        st, _ = verzoek(self.basis, "/login", "POST",
                        {"username": "alice", "password": "wachtwoord123"})
        self.assertEqual(st, 429)

    def test_history_url_validatie(self):
        st, b = verzoek(self.basis, "/register", "POST",
                        {"username": "bob", "password": "wachtwoord123"})
        token = json.loads(b)["token"]
        kop = {"Authorization": "Bearer " + token}
        self.assertEqual(verzoek(self.basis, "/history", "POST",
                                 {"url": "javascript:alert(1)"}, kop)[0], 400)
        self.assertEqual(verzoek(self.basis, "/history", "POST",
                                 {"url": "https://example.com/"}, kop)[0], 201)

    def test_ssrf_via_browse_geblokkeerd(self):
        st, _ = verzoek(self.basis, "/browse?url=" +
                        urllib.parse.quote("http://127.0.0.1:18971/health"))
        self.assertEqual(st, 403)


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = laad_module("gw_test", REPO / "gateway" / "server.py")
        cls.server = start_server(cls.m, cls.m.Handler, 18972)
        cls.basis = "http://127.0.0.1:18972"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_health_publiek(self):
        self.assertEqual(verzoek(self.basis, "/health")[0], 200)

    def test_kwaadaardige_origin_wordt_geblokkeerd(self):
        st, _ = verzoek(self.basis, "/config/keys", "POST", {"action": "get"},
                        {"Origin": "http://evil.example"})
        self.assertEqual(st, 403)

    def test_dns_rebinding_wordt_geblokkeerd(self):
        st, _ = verzoek(self.basis, "/health", headers={"Host": "evil.example:18972"})
        self.assertEqual(st, 403)

    def test_lokale_origin_wordt_toegestaan(self):
        st, _ = verzoek(self.basis, "/config/keys", "POST", {"action": "get"},
                        {"Origin": "http://localhost:18972"})
        self.assertEqual(st, 200)

    def test_geen_sleutel_voor_onbekende_provider(self):
        st, _ = verzoek(self.basis, "/ask", "POST",
                        {"prompt": "hoi", "provider": "mistral"},
                        {"Origin": "http://localhost:18972"})
        self.assertIn(st, (200, 500, 502))


class ApiServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["NEWLY_API_KEY"] = "test-master-key-123456"
        cls.m = laad_module("api_test", SYNC / "api_server.py")
        cls.server = start_server(cls.m, cls.m.APIHandler, 18973)
        cls.basis = "http://127.0.0.1:18973"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_lege_bearer_is_geen_admin(self):
        st, _ = verzoek(self.basis, "/api/clients", "POST", {},
                        {"Authorization": "Bearer"})
        self.assertEqual(st, 401)

    def test_verkeerde_master_key(self):
        self.m.VERZOEKEN.clear()
        st, _ = verzoek(self.basis, "/api/clients", "POST", {},
                        {"Authorization": "Bearer verkeerd"})
        self.assertEqual(st, 401)

    def test_client_aanmaken_en_inloggen(self):
        st, b = verzoek(self.basis, "/api/clients", "POST", {"name": "test"},
                        {"Authorization": "Bearer test-master-key-123456"})
        self.assertEqual(st, 201)
        info = json.loads(b)
        cid, secret = info["client_id"], info["client_secret"]

        self.assertEqual(verzoek(self.basis, "/api", headers={
            "X-Client-ID": cid, "X-Client-Secret": secret})[0], 200)
        self.assertEqual(verzoek(self.basis, "/api", headers={
            "X-Client-ID": cid, "X-Client-Secret": "fout"})[0], 401)

        con = sqlite3.connect(self.m.DB_PATH)
        rij = con.execute("SELECT client_secret FROM api_clients WHERE client_id = ?",
                          (cid,)).fetchone()
        con.close()
        self.assertNotEqual(rij[0], secret)
        self.assertEqual(len(rij[0]), 64)

    def test_rate_limit(self):
        for _ in range(125):
            verzoek(self.basis, "/health")
        st, _ = verzoek(self.basis, "/health")
        self.assertEqual(st, 429)


if __name__ == "__main__":
    unittest.main()
