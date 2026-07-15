"""Pure MIME helpers for adding/listing/removing attachments on an existing
Gmail draft's raw message, while PRESERVING the body (set_content / plain+html
alternative) structure.

Stdlib only (email/mimetypes) — no repo or network dependencies — so it is
unit-testable in isolation. Used by gmail/gmail_tools.py's add_attachment_from_url
/ list_attachments / remove_attachment tools (Loma Phase-2 attachment support):
fetch the draft raw, transform here, then drafts().update with the result.
"""
from __future__ import annotations

import email
import mimetypes
from email.policy import SMTP


def split_content_type(content_type, filename):
    """Return (maintype, subtype). Prefer an explicit content_type; otherwise
    guess from the filename; otherwise application/octet-stream."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    if "/" not in ctype:
        guessed, _ = mimetypes.guess_type(filename or "", strict=False)
        ctype = (guessed or "application/octet-stream").lower()
    maintype, _, subtype = ctype.partition("/")
    if not maintype or not subtype:
        return "application", "octet-stream"
    return maintype, subtype


def _parse(raw_bytes):
    return email.message_from_bytes(raw_bytes, policy=SMTP)


def add_attachment_to_raw(raw_bytes, filename, data, content_type=None):
    """Parse a draft's raw MIME, add ``data`` as an attachment, return new raw
    bytes. The existing body (plain and/or html alternative) is preserved;
    EmailMessage restructures to multipart/mixed automatically."""
    msg = _parse(raw_bytes)
    maintype, subtype = split_content_type(content_type, filename)

    # add_attachment wants str for a text/* part and bytes otherwise.
    if maintype == "text":
        try:
            text = data.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            msg.add_attachment(
                data, maintype="application", subtype="octet-stream", filename=filename
            )
        else:
            msg.add_attachment(text, subtype=subtype, filename=filename)
    else:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    return msg.as_bytes(policy=SMTP)


def list_attachments_from_raw(raw_bytes):
    """Return a list of {filename, content_type, size} for each attachment."""
    msg = _parse(raw_bytes)
    out = []
    for part in msg.iter_attachments():
        try:
            content = part.get_content()
            size = len(content.encode("utf-8", "replace")) if isinstance(content, str) else len(content)
        except Exception:
            payload = part.get_payload(decode=True)
            size = len(payload) if payload else 0
        out.append(
            {
                "filename": part.get_filename(),
                "content_type": part.get_content_type(),
                "size": size,
            }
        )
    return out


def _remove_first_attachment(part, filename):
    """Depth-first: drop the first attachment part with a matching filename from
    its parent multipart payload. Returns True if one was removed."""
    if not part.is_multipart():
        return False
    payload = part.get_payload()  # the internal list for a multipart part
    for i, sub in enumerate(list(payload)):
        if sub.get_content_disposition() == "attachment" and sub.get_filename() == filename:
            del payload[i]
            return True
    for sub in payload:
        if sub.is_multipart() and _remove_first_attachment(sub, filename):
            return True
    return False


def remove_attachment_from_raw(raw_bytes, filename):
    """Remove the first attachment whose filename matches. Returns
    (new_raw_bytes, removed: bool). Body structure is preserved."""
    msg = _parse(raw_bytes)
    removed = _remove_first_attachment(msg, filename)
    return msg.as_bytes(policy=SMTP), removed
