"""The mailing list, via Buttondown. One function, called once, at signup, only if the person ticked
the (unticked-by-default) box for it. A failure here must never break account creation: Buttondown
being down is not the visitor's problem."""
import json
import os
import urllib.error
import urllib.request


def enabled():
    return bool(os.environ.get("BUTTONDOWN_API_KEY"))


def subscribe(email):
    """Best-effort. Returns True on success; logs nothing, raises nothing, since a newsletter signup
    failing silently is far better than it breaking someone's account creation."""
    key = os.environ.get("BUTTONDOWN_API_KEY")
    if not key or not email:
        return False
    body = json.dumps({"email": email, "tags": ["whisker-wire"]}).encode()
    req = urllib.request.Request("https://api.buttondown.email/v1/subscribers", data=body, method="POST",
                                 headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        return e.code == 400 and b"already" in e.read().lower()   # already subscribed counts as success
    except Exception:
        return False
