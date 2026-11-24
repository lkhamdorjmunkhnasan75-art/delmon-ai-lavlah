"""Run only on disposable CI DB after integration fixtures have been loaded."""
import unittest
from playwright.sync_api import sync_playwright, expect

class BrowserUI(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.chromium.launch()
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 360, "height": 800}, is_mobile=True, has_touch=True)
        self.page.goto("http://127.0.0.1:8000/")
        expect(self.page.locator("#category option[value=services]")).to_have_count(1)

    def search(self, query="", category=""):
        self.page.locator("#q").fill(query)
        self.page.locator("#category").select_option(category)
        self.page.get_by_role("button", name="Хайх", exact=True).click()

    def test_mobile_search_and_filter(self):
        self.search("монгол", "services")
        expect(self.page.locator("#results article")).to_have_count(1)
        expect(self.page.locator("#results h2")).to_have_text("Монгол Алфа")
        expect(self.page.get_by_role("link", name="Эх сурвалж")).to_have_attribute("href", "https://example.test/1")
        for width in (320,360,390,768):
            self.page.set_viewport_size({"width":width,"height":800})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        self.search("монгол", "trade")
        expect(self.page.locator("#results h2")).to_have_text("Монгол Бета")
        self.search("монгол")
        expect(self.page.locator("#results article")).to_have_count(2)

    def test_empty_and_error_recovery(self):
        self.search("nonexistent")
        expect(self.page.locator("#status")).to_have_text("Тохирох мэдээлэл олдсонгүй.")
        self.page.route("**/v1/directory?*", lambda route: route.fulfill(status=503,body="unavailable"))
        self.search("монгол")
        expect(self.page.locator("#status")).to_have_text("Түр алдаа гарлаа. Дахин хайна уу.")
        expect(self.page.locator("#results article")).to_have_count(0)
        self.page.unroute("**/v1/directory?*")
        self.search("монгол")
        expect(self.page.locator("#results article")).to_have_count(2)

    def test_category_error(self):
        self.page.route("**/v1/directory/categories",lambda route: route.fulfill(status=503,body="unavailable"))
        self.page.reload()
        expect(self.page.locator("#category-status")).to_contain_text("Ангиллыг ачаалж чадсангүй")
        self.page.locator("#q").fill("Алфа")
        self.page.get_by_role("button",name="Хайх",exact=True).click()
        expect(self.page.locator("#results h2")).to_have_text("Монгол Алфа")
