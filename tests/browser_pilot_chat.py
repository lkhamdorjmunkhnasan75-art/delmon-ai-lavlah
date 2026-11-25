import unittest
from playwright.sync_api import sync_playwright, expect

class PilotChatBrowser(unittest.TestCase):
    def setUp(self):
        pw=sync_playwright().start()
        self.addCleanup(pw.stop)
        browser=pw.chromium.launch()
        self.addCleanup(browser.close)
        self.page=browser.new_page(viewport={"width":360,"height":800},is_mobile=True,has_touch=True,service_workers="block")
        self.page.goto("http://127.0.0.1:3000/")
        expect(self.page.locator("#category option[value=services]")).to_have_count(1)
        self.chat=self.page.get_by_role("region",name="DELMON чат")

    def ask(self,q):
        self.chat.locator("#pilot-question").fill(q)
        self.chat.get_by_role("button",name="Асуух",exact=True).click()

    def test_real_grounded_answer_and_rating(self):
        self.ask("Altan nar zasvar baina uu?")
        expect(self.chat.get_by_role("heading",name="ТУРШИЛТ — Алтан нар засвар")).to_be_visible()
        expect(self.chat.get_by_role("link",name="Эх сурвалж")).to_have_attribute("href","https://pilot.example.test/0")
        expect(self.chat.locator(".chat-source")).to_contain_text("Хүчинтэй хүртэл:")
        self.chat.get_by_role("button",name="Тустай",exact=True).click()
        expect(self.chat.get_by_role("button",name="Тустай",exact=True)).to_have_attribute("aria-pressed","true")
        for width in (320,360,390,768):
            self.page.set_viewport_size({"width":width,"height":800})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))

    def test_clarification_no_result_clear(self):
        self.ask("Үнэ хэд вэ?")
        expect(self.chat.locator(".chat-turn").last).to_contain_text("тодруулна уу")
        self.ask("Цагаан уул хүргэлт")
        expect(self.chat.locator(".chat-turn").last).to_contain_text("Баталгаажсан тохирох мэдээлэл олдсонгүй.")
        expect(self.chat.locator(".chat-source")).to_have_count(0)
        self.chat.get_by_role("button",name="Чат цэвэрлэх").click()
        expect(self.chat.locator(".chat-turn")).to_have_count(0)

    def test_error_and_retry(self):
        pattern="**/api/pilot/ask"
        self.page.route(pattern,lambda r:r.fulfill(status=503,body="private error"))
        self.ask("Алтан нар засвар")
        expect(self.chat.get_by_role("alert")).to_contain_text("Түр алдаа")
        expect(self.chat.locator("#pilot-question")).to_have_value("Алтан нар засвар")
        self.page.unroute(pattern)
        self.chat.get_by_role("button",name="Асуух",exact=True).click()
        expect(self.chat.locator(".chat-source")).to_have_count(1)
        expect(self.chat.get_by_role("alert")).to_have_count(0)

    def test_loading_and_safe_rendering(self):
        import time
        def delayed(route):
            time.sleep(.4)
            route.fulfill(json={"status":"matched","answer":"<script>bad()</script>","items":[{"name":"<img src=x onerror=bad()>","description":"Туршилт","source_url":"javascript:alert(1)","verified_at":"2026-01-01","expires_at":"2027-01-01"}]})
        self.page.route("**/api/pilot/ask",delayed)
        self.ask("Алтан нар")
        expect(self.chat.get_by_role("button",name="Асуух",exact=True)).to_be_disabled()
        expect(self.chat.locator(".chat-turn")).to_contain_text("<script>bad()</script>")
        expect(self.chat.locator(".chat-source img")).to_have_count(0)
        expect(self.chat.get_by_role("link",name="Эх сурвалж")).to_have_count(0)

    def test_proxy_origin_and_size(self):
        endpoint="http://127.0.0.1:3000/api/pilot/ask"
        req=self.page.request
        self.assertEqual(req.post(endpoint,data={"question":"Алтан нар"},headers={"Origin":"https://example.test"}).status,403)
        self.assertEqual(req.post(endpoint,data={"question":"а"*5000},headers={"Origin":"http://127.0.0.1:3000"}).status,413)
