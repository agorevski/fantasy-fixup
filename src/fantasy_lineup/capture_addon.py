"""mitmproxy addon: record FantasyPros traffic from your own browser session.

Run with:  .venv/bin/mitmdump -s src/fantasy_lineup/capture_addon.py -p 8080

Only requests to *.fantasypros.com are kept; everything else is ignored.
Two outputs, both under var/capture/ (gitignored):
  - requests.jsonl : method, URL, status, response size and type, and a redacted
                     view of headers (cookie/auth values replaced by "<redacted>").
  - auth.json      : full request headers from the most recent FantasyPros request,
                     written chmod 600, so later scripts can reuse the session.
Response bodies for JSON endpoints are saved to var/capture/bodies/ so the API
shapes can be read without re-running the browser.
"""

import hashlib
import json
import os
from pathlib import Path

from mitmproxy import http

# Loaded by mitmdump as a script, so it does not import the package. This file is src/fantasy_lineup/.
OUT = Path(__file__).resolve().parents[2] / "var" / "capture"
BODIES = OUT / "bodies"
SENSITIVE = {"cookie", "authorization", "set-cookie", "x-csrf-token", "x-xsrf-token"}
MAX_BODY = 2_000_000


def _redact(headers) -> dict:
    out = {}
    for k, v in headers.items(multi=True):
        out[k] = "<redacted>" if k.lower() in SENSITIVE else v
    return out


class FantasyProsCapture:
    def __init__(self) -> None:
        OUT.mkdir(mode=0o700, exist_ok=True)
        BODIES.mkdir(mode=0o700, exist_ok=True)

    def response(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        if not (host == "fantasypros.com" or host.endswith(".fantasypros.com")):
            return

        req, resp = flow.request, flow.response
        ctype = (resp.headers.get("content-type") or "") if resp else ""
        entry = {
            "method": req.method,
            "url": req.pretty_url,
            "status": resp.status_code if resp else None,
            "content_type": ctype,
            "request_headers": _redact(req.headers),
        }

        if resp is not None and "json" in ctype and len(resp.raw_content or b"") <= MAX_BODY:
            name = hashlib.sha1(req.pretty_url.encode()).hexdigest()[:12] + ".json"
            path = BODIES / name
            path.write_bytes(resp.raw_content or b"")
            os.chmod(path, 0o600)
            entry["body_file"] = str(path.relative_to(OUT))

        with open(OUT / "requests.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

        # Full headers (including cookies) are needed to reuse the session.
        # Stored only in a 0600 file; never logged in redacted form.
        auth = {k: v for k, v in req.headers.items(multi=True)}
        if "cookie" in {k.lower() for k in auth}:
            auth_path = OUT / "auth.json"
            auth_path.write_text(json.dumps({"url": req.pretty_url, "headers": auth}, indent=2))
            os.chmod(auth_path, 0o600)


addons = [FantasyProsCapture()]
