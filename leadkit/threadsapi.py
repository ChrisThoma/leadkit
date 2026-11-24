"""The Threads API calls behind the Threads page and the reply buttons: who
the token is, search, mentions, publishing (a post or a reply), our own posts
with their replies and insights, and deleting.

Every request goes through call(), so tests replace that one function. Each
action here is started by you on a page or command; nothing runs on a timer.
"""
import json, time, urllib.error, urllib.parse, urllib.request

GRAPH = "https://graph.threads.net/v1.0"
POST_FIELDS = "id,text,username,permalink,timestamp,is_reply"
METRICS = ["views", "likes", "replies", "reposts", "quotes"]


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"{status}: {body[:300]}")
        self.status, self.body = status, body


def call(path, tok, params=None, method="GET"):
    params = dict(params or {}, access_token=tok)
    url = f"{GRAPH}/{path.lstrip('/')}"
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace")) from None


def me(tok):
    return call("me", tok, {"fields": "id,username"})


def search(tok, q, limit=25):
    """Recent public posts with the keyword. Until App Review approves
    threads_keyword_search this returns only our own posts."""
    return call("keyword_search", tok, {"q": q, "search_type": "RECENT", "limit": limit,
                                        "fields": POST_FIELDS}).get("data", [])


def mentions(tok, limit=25):
    return call("me/mentions", tok, {"limit": limit, "fields": POST_FIELDS}).get("data", [])


def own_posts(tok, limit=10):
    return call("me/threads", tok, {"limit": limit, "fields": POST_FIELDS}).get("data", [])


def own_replies(tok, limit=100):
    """Every reply we've posted, newest first. Follows `after` cursors until a
    page has none. Under other people's posts these carry no root_post or
    replied_to, so the link back to a lead lives in the lead row. The API may
    hand a cursor on the last page too, so an empty page or a repeated cursor
    also ends the walk."""
    out, after = [], None
    while True:
        params = {"fields": "id,text,permalink,timestamp", "limit": limit} | ({"after": after} if after else {})
        page = call("me/replies", tok, params)
        out += page.get("data", [])
        last, after = after, ((page.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or after == last or not page.get("data"):
            return out


def replies(tok, media_id, own=""):
    """Replies to one of our posts, leaving out our own."""
    out = call(f"{media_id}/replies", tok, {"fields": POST_FIELDS}).get("data", [])
    return [r for r in out if (r.get("username") or "").lower() != own.lower()]


def insights(tok, media_id):
    data = call(f"{media_id}/insights", tok, {"metric": ",".join(METRICS)}).get("data", [])
    return {m["name"]: (m.get("values") or [{}])[0].get("value", m.get("total_value", {}).get("value", 0))
            for m in data}


def publish(tok, text, reply_to=None, wait=1.0):
    """Create a text container and publish it. Returns the new post's id and permalink."""
    params = {"media_type": "TEXT", "text": text}
    if reply_to:
        params["reply_to_id"] = reply_to
    creation = call("me/threads", tok, params, method="POST")["id"]
    # A container can take a moment before it publishes; text ones are quick.
    for attempt in range(3):
        try:
            post = call("me/threads_publish", tok, {"creation_id": creation}, method="POST")
            break
        except ApiError:
            if attempt == 2:
                raise
            time.sleep(wait * (attempt + 1))
    post_id = post["id"]
    return {"id": post_id, "permalink": call(post_id, tok, {"fields": "permalink"}).get("permalink", "")}


def delete(tok, media_id):
    return call(media_id, tok, method="DELETE")
