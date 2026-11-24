"""The Threads page's routes and the drafts page's Post reply button."""
import json, sys, unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leadkit import drafts, threads, threadsapi, threadspage  # noqa: E402
from helpers import TempProduct, ago  # noqa: E402
from test_threads_api import OLD, FakeApi, post  # noqa: E402


class PageTest(unittest.TestCase):
    def setUp(self):
        self.t = TempProduct()
        self.t.write("Threads", [
            {"url": "https://www.threads.com/@a/post/PA", "id": "100", "reply": "Try it.", "status": "draft",
             "posted": ago(0), "author": "a"},
            {"url": "https://www.threads.com/@b/post/PB", "reply": "Copy me.", "status": "draft",
             "posted": ago(0), "author": "b"},
            {"url": "https://www.threads.com/@c/post/PC", "id": "300", "reply_id": "R9", "status": "posted"},
        ], fields=OLD + ["id", "reply_id"])
        self.page = threadspage.Page([self.t.p], port=8765, token=lambda: "tok")

    def tearDown(self):
        self.t.close()

    def request(self, method, path, body=None):
        status, headers, out = self.page.handle(method, path, json.dumps(body).encode() if body else b"")
        return status, headers, (json.loads(out) if headers.get("Content-Type") == "application/json" else out)

    def test_post_reply_button_only_on_cards_with_a_post_id(self):
        page = drafts.render([self.t.p])[1]
        self.assertEqual(page.count('class="post-reply"'), 1)
        self.assertIn('data-url="https://www.threads.com/@a/post/PA"', page)

    def test_reply_route_posts_through_the_api(self):
        api = FakeApi()
        with mock.patch.object(threadsapi, "call", api):
            status, _, out = self.request("POST", "/threads-reply", {"product": "knitwit",
                                                                      "url": "https://www.threads.com/@a/post/PA"})
        self.assertEqual(status, 200)
        self.assertTrue(out["permalink"].endswith("/R1"))
        self.assertEqual(sum(1 for c in api.calls if c[1] == "me/threads_publish"), 1)

    def test_reply_route_reports_a_refusal(self):
        with mock.patch.object(threadsapi, "call", FakeApi()):
            status, _, out = self.request("POST", "/threads-reply", {"product": "knitwit",
                                                                      "url": "https://www.threads.com/@b/post/PB"})
        self.assertEqual(status, 400)
        self.assertIn("copy the reply", out["error"])

    def test_search_returns_posts(self):
        api = FakeApi({("GET", "keyword_search"): {"data": [post("5", "someone")]}})
        with mock.patch.object(threadsapi, "call", api):
            status, _, out = self.request("GET", "/api/search?q=knitting")
        self.assertEqual(status, 200)
        self.assertEqual(out["posts"][0]["id"], "5")
        self.assertEqual(api.calls[0][2]["q"], "knitting")

    def test_add_lead_route(self):
        status, _, out = self.request("POST", "/api/add-lead", {"product": "knitwit", "post": post("6", "someone"),
                                                                 "how": "search knitting"})
        self.assertEqual(status, 200)
        self.assertEqual(self.t.read("Threads")[-1]["id"], "6")

    def test_publish_needs_text(self):
        api = FakeApi()
        with mock.patch.object(threadsapi, "call", api):
            self.assertEqual(self.request("POST", "/api/publish", {"text": "  "})[0], 400)
            status, _, out = self.request("POST", "/api/publish", {"text": "Hello"})
        self.assertEqual(status, 200)
        self.assertEqual(api.calls[0][2]["text"], "Hello")

    def test_delete_clears_the_lead_that_reply_belonged_to(self):
        api = FakeApi()
        with mock.patch.object(threadsapi, "call", api):
            status, _, _ = self.request("POST", "/api/delete", {"id": "R9"})
        self.assertEqual(status, 200)
        self.assertEqual(api.calls[-1][:2], ("DELETE", "R9"))
        self.assertEqual(self.t.read("Threads")[2]["status"], "deleted")

    def test_signin_carries_port_and_a_nonce_the_callback_checks(self):
        status, headers, _ = self.request("GET", "/threads-signin")
        self.assertEqual(status, 302)
        q = parse_qs(urlparse(headers["Location"]).query)
        port, nonce = q["state"][0].split(".")
        self.assertEqual(port, "8765")
        with mock.patch.object(threads, "exchange", return_value={"access_token": "T", "expires_in": 5184000}) as ex, \
                mock.patch.object(threads, "save_token") as save:
            self.assertEqual(self.request("GET", "/threads-callback?code=abc&state=8765.wrong")[0], 400)
            ex.assert_not_called()
            status, headers, _ = self.request("GET", f"/threads-callback?code=abc%23_&state=8765.{nonce}")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "/threads")
        ex.assert_called_once_with("abc")
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
