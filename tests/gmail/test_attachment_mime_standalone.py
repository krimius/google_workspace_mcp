#!/usr/bin/env python3
"""Standalone (dependency-free) tests for gmail/attachment_mime.py.

The module uses only stdlib (email/base64/mimetypes), so these run under any
Python without `uv sync`:  python tests/gmail/test_attachment_mime_standalone.py

Verifies the Loma Phase-2 attachment mechanics: add an attachment to an existing
draft's raw MIME while PRESERVING the plain/html body structure, list, and remove.
"""
import os
import sys
import base64
from email.message import EmailMessage
from email.policy import SMTP

# Import the pure module directly (no repo deps).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gmail"))
import attachment_mime as am  # noqa: E402

failures = []


def check(name, cond):
    if cond:
        print(f"  PASS  {name}")
    else:
        failures.append(name)


def _base_draft_raw(with_html=True):
    """A draft with a plain body and (optionally) an html alternative."""
    msg = EmailMessage(policy=SMTP)
    msg["To"] = "someone@example.com"
    msg["Subject"] = "Test draft"
    msg.set_content("Hello Krim,\n\nThis is the body.")
    if with_html:
        msg.add_alternative("<p>Hello Krim,</p><p>This is the body.</p>", subtype="html")
    return msg.as_bytes(policy=SMTP)


PDF = b"%PDF-1.4 fake pdf bytes"

# ── split_content_type ───────────────────────────────────────────────────────
check("split explicit application/pdf", am.split_content_type("application/pdf", "x.pdf") == ("application", "pdf"))
check("split guesses from filename", am.split_content_type(None, "report.pdf") == ("application", "pdf"))
check("split unknown -> octet-stream", am.split_content_type(None, "x.unknownext") == ("application", "octet-stream"))
check("split ignores charset param", am.split_content_type("application/pdf; charset=binary", "x.pdf") == ("application", "pdf"))

# ── add_attachment_to_raw ────────────────────────────────────────────────────
raw = _base_draft_raw(with_html=True)
new_raw = am.add_attachment_to_raw(raw, "report.pdf", PDF, "application/pdf")
atts = am.list_attachments_from_raw(new_raw)
check("add: attachment now listed", len(atts) == 1)
check("add: correct filename", atts and atts[0]["filename"] == "report.pdf")
check("add: correct content_type", atts and atts[0]["content_type"] == "application/pdf")
check("add: correct size", atts and atts[0]["size"] == len(PDF))

# body must be preserved (both plain and html alternatives survive)
parsed = __import__("email").message_from_bytes(new_raw, policy=SMTP)
plain = parsed.get_body(preferencelist=("plain",))
htmlp = parsed.get_body(preferencelist=("html",))
check("add: plain body preserved", plain is not None and "This is the body." in plain.get_content())
check("add: html body preserved", htmlp is not None and "<p>Hello Krim,</p>" in htmlp.get_content())

# ── add to a plain-only draft (no html alternative) ─────────────────────────
raw_plain = _base_draft_raw(with_html=False)
new_plain = am.add_attachment_to_raw(raw_plain, "notes.txt", b"hi there", "text/plain")
check("add(plain-only): listed", len(am.list_attachments_from_raw(new_plain)) == 1)
pp = __import__("email").message_from_bytes(new_plain, policy=SMTP).get_body(preferencelist=("plain",))
check("add(plain-only): body preserved", pp is not None and "This is the body." in pp.get_content())

# ── two attachments ─────────────────────────────────────────────────────────
two = am.add_attachment_to_raw(new_raw, "second.csv", b"a,b,c\n1,2,3", "text/csv")
names = sorted(a["filename"] for a in am.list_attachments_from_raw(two))
check("add: two attachments coexist", names == ["report.pdf", "second.csv"])

# ── remove_attachment_from_raw ───────────────────────────────────────────────
removed_raw, removed = am.remove_attachment_from_raw(two, "report.pdf")
check("remove: reports removed", removed is True)
left = am.list_attachments_from_raw(removed_raw)
check("remove: only the other remains", [a["filename"] for a in left] == ["second.csv"])
rp = __import__("email").message_from_bytes(removed_raw, policy=SMTP).get_body(preferencelist=("plain",))
check("remove: body preserved", rp is not None and "This is the body." in rp.get_content())

_, removed_none = am.remove_attachment_from_raw(two, "does-not-exist.pdf")
check("remove: missing -> False", removed_none is False)

if failures:
    print("\nFAILURES:")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)
print("\nALL TESTS PASSED")
