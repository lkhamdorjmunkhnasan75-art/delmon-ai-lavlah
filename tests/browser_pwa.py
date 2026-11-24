import unittest
from playwright.sync_api import sync_playwright, expect

class PwaBrowser(unittest.TestCase):
    def setUp(self):
        self.pw=sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser=self.pw.chromium.launch()
        self.addCleanup(self.browser.close)
        self.page=self.browser.new_page(viewport={"width":360,"height":800},is_mobile=True,has_touch=True)
        self.page.goto("http://127.0.0.1:3000/")
        expect(self.page.locator("#category option[value=services]")).to_have_count(1)

    def search(self,q,category=""):
        self.page.locator("#q").fill(q)
        self.page.locator("#category").select_option(category)
        self.page.get_by_role("button",name="Хайх",exact=True).click()

    def test_search_mobile_and_error(self):
        self.search("монгол","services")
        expect(self.page.locator("#results h2")).to_have_text("Монгол Алфа")
        expect(self.page.get_by_role("link",name="Эх сурвалж")).to_have_attribute("href","https://example.test/1")
        expect(self.page.locator("#category option[value=services]")).to_have_text("Үйлчилгээ")
        for width in (320,360,390,768):
            self.page.set_viewport_size({"width":width,"height":800})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.search("монгол","trade")
        expect(self.page.locator("#results h2")).to_have_text("Монгол Бета")
        self.search("nonexistent")
        expect(self.page.locator("#status")).to_have_text("Тохирох мэдээлэл олдсонгүй.")
        self.page.route("**/api/directory?*",lambda r:r.fulfill(status=503,body="unavailable"))
        self.search("монгол")
        expect(self.page.locator("#status")).to_have_text("Түр алдаа гарлаа. Дахин хайна уу.")
        self.page.unroute("**/api/directory?*")
        self.search("монгол")
        expect(self.page.locator("#results article")).to_have_count(2)

    def test_manifest_worker_and_headers(self):
        req=self.page.request
        manifest=req.get("http://127.0.0.1:3000/manifest.webmanifest").json()
        self.assertEqual(manifest["display"],"standalone")
        for icon in manifest["icons"]:
            response=req.get("http://127.0.0.1:3000"+icon["src"])
            self.assertEqual(response.status,200)
            self.assertEqual(response.headers["content-type"],"image/png")
        self.page.evaluate("navigator.serviceWorker.ready")
        response=req.get("http://127.0.0.1:3000/api/directory")
        self.assertIn("no-store",response.headers["cache-control"])
        self.assertEqual(response.headers["x-content-type-options"],"nosniff")
        self.assertEqual(req.get("http://127.0.0.1:3000/api/directory/private").status,404)
        self.assertEqual(self.page.evaluate("caches.keys()"),[])

    def test_nonce_and_injection_blocked(self):
        import re
        first=self.page.request.get("http://127.0.0.1:3000/")
        second=self.page.request.get("http://127.0.0.1:3000/")
        a=first.headers["content-security-policy"]
        b=second.headers["content-security-policy"]
        self.assertNotIn("unsafe-inline",a)
        self.assertNotIn("unsafe-eval",a)
        self.assertIn("no-store",first.headers["cache-control"])
        nonce=re.search(r"'nonce-([^']+)'",a).group(1)
        self.assertNotIn(nonce,b)
        # Use a parser-inserted script in a fresh document, not CDP evaluation
        # as the injection mechanism. Preserve the actual response CSP.
        context=self.browser.new_context(service_workers="block")
        self.addCleanup(context.close)
        page=context.new_page()
        def inject(route):
            original=route.fetch()
            html=original.text().replace("</body>", "<script>window.__injected = true;</script></body>")
            self.assertIn("<script>window.__injected = true;</script>", html)
            route.fulfill(response=original,body=html)
        page.route("http://127.0.0.1:3000/",inject)
        navigation=page.goto("http://127.0.0.1:3000/")
        self.assertIn("'nonce-",navigation.headers["content-security-policy"])
        expect(page.locator("#category option[value=services]")).to_have_count(1)
        self.assertFalse(page.evaluate("window.__injected === true"))
        self.search("монгол","services")
        expect(self.page.locator("#results h2")).to_have_text("Монгол Алфа")
