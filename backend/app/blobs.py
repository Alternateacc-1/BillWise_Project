"""Uploaded file storage. A local directory now, S3 behind the same interface.

SECURITY: the stored filename is derived ONLY from a server-generated bill id
and a suffix taken from a fixed allowlist. The client's filename never
reaches the filesystem, so there is no path traversal to get wrong.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BLOB_DIR = REPO_ROOT / "data" / "blobs"

#: Upload limits, enforced BEFORE any billable call is made. Textract is
#: priced per page, so a careless 400-page PDF is a real cost event.
#: See docs/ARCHITECTURE.md, cost controls.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024        # 10 MB
MAX_PAGES = 10

#: content type -> file suffix. An upload whose type is not a key here is
#: rejected; nothing else is accepted, and the suffix is never taken from the
#: client's filename.
ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class UploadRejected(Exception):
    """Raised with a message safe to show the user."""


def validate(content: bytes, content_type: str) -> str:
    """Check an upload and return the suffix to store it under."""
    suffix = ALLOWED_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if suffix is None:
        raise UploadRejected(
            "Please upload a PDF, JPG, PNG or WEBP file."
        )
    if not content:
        raise UploadRejected("That file appears to be empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
            "Please upload a smaller scan."
        )
    if suffix == ".pdf":
        pages = count_pdf_pages(content)
        if pages is not None and pages > MAX_PAGES:
            raise UploadRejected(
                f"That PDF has {pages} pages; we handle up to {MAX_PAGES}."
            )
    return suffix


def count_pdf_pages(content: bytes) -> int | None:
    """Best-effort page count. None when it cannot be determined.

    Counted here, before anything billable runs, rather than discovering the
    size after paying per page for it.
    """
    try:
        import pdfplumber
        import io

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def put(bill_id: str, content: bytes, suffix: str) -> str:
    """Store the bytes. Returns an opaque key, never a client-supplied path."""
    BLOB_DIR.mkdir(parents=True, exist_ok=True)
    # bill_id is server-generated (secrets.token_urlsafe) and the suffix comes
    # from ALLOWED_TYPES, so this path cannot be steered by the client.
    key = f"{bill_id}{suffix}"
    (BLOB_DIR / key).write_bytes(content)
    return key


def path_for(key: str) -> Path | None:
    candidate = (BLOB_DIR / key).resolve()
    # Belt and braces: refuse anything that escaped the blob directory.
    if not str(candidate).startswith(str(BLOB_DIR.resolve())):
        return None
    return candidate if candidate.exists() else None
