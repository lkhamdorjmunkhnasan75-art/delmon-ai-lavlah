import os
import unittest
from playwright.sync_api import sync_playwright,expect
from test_identity_isolation import token

ORIGIN=os.environ.get("PILOT_CHAT_ORIGIN","http://127.0.0.1:3001")

class IdentityChatBrowser(unittest.TestCase):
    def test_identity_chat_feedback_logout(self):
        t=token()
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            try:
                page=browser.new_page(viewport={"width":360,"height":800},is_mobile=True,has_touch=True,service_workers="block")
                page.goto(ORIGIN+"/")
                chat=page.get_by_role("region",name="DELMON чат")
                chat.get_by_role("button",name="Identity token ашиглах").click()
                chat.locator("#identity-token").fill(t)
                chat.get_by_role("button",name="Identity нэвтрэх").click()
                expect(chat.locator("#pilot-question")).to_be_visible()
                chat.locator("#pilot-question").fill("Altan nar zaswariin medeelel")
                chat.get_by_role("button",name="Асуух",exact=True).click()
                expect(chat.get_by_role("heading",name="ТУРШИЛТ — Алтан нар засвар")).to_be_visible()
                chat.get_by_role("button",name="Тустай",exact=True).click()
                expect(chat.get_by_text("Үнэлгээ серверт хадгалагдлаа.")).to_be_visible()
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                self.assertEqual(page.evaluate("localStorage.length + sessionStorage.length"),0)
                with page.expect_response(lambda r:r.url.endswith("/api/pilot/identity-revoke")) as response:
                    chat.get_by_role("button",name="Гарах",exact=True).click()
                self.assertEqual(response.value.status,200)
                expect(chat.locator(".chat-turn")).to_have_count(0)
                r=page.request.post(ORIGIN+"/api/pilot/identity-chat",data={"question":"Алтан нар"},headers={"Origin":ORIGIN,"Authorization":"Bearer "+t})
                self.assertEqual(r.status,401)
            finally:browser.close()
