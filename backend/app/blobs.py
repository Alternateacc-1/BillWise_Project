"""Uploaded file storage. A local directory now, S3 behind the same interface.

SECURITY: the stored filename is derived ONLY from a server-generated bill id
and a suffix taken from a fixed allowlist. The client's filename never
reaches the filesystem, so there is no path traversal to get wrong.
"""

from __future__ import annotations

from pathlib import Path

from . import config

REPO_ROOT = Path(__file__).resolve().parents[2]
BLOB_DIR = REPO_ROOT / "data" / "blobs"

#: Upload limits, enforced BEFORE any billable call is made. Textract is
#: priced per page, so a careless 400-page PDF is a real cost event.
#: See docs/ARCHITECTURE.md, cost controls.
# 4 MB. NOT a policy choice -- API Gateway base64-encodes the body into the
# Lambda event (+~33%) and Lambda caps a synchronous event at 6 MB, so ~4.5 MB
# of file is the hard ceiling. Measured 2026-09-20: 4 MB arrived, 5 MB and
# 8 MB were refused with 413 by the gateway, before this code ran.
#
# Keeping 10 MB here would mean promising something the transport refuses --
# and the gateway's 413 carries no CORS headers, so a browser cannot even read
# the reason and shows a bare "Network error".
MAX_UPLOAD_BYTES = 4 * 1024 * 1024         # 4 MB
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


#: The opening bytes of each format we accept, as hex.
#:
#: THE CLIENT SENDS THE CONTENT TYPE, SO IT IS A CLAIM, NOT A FACT -- and
#: until 2026-09-20 we took it at face value. The PDF page-count guard below
#: hangs off that claim: a PDF declared `image/jpeg` was given suffix `.jpg`,
#: skipped the page check entirely, and went to Textract -- which detects the
#: real format itself and bills PER PAGE.
#:
#: Verified against the live API before fixing: a PDF posted as `image/jpeg`
#: returned HTTP 200 and was processed. One word in a header defeated the only
#: thing standing between a public, unauthenticated endpoint and an unbounded
#: Textract bill.
#:
#: Hex rather than escape sequences deliberately -- `\xff\xd8\xff` gets
#: mangled by shells and editors, and a silently corrupted magic number would
#: reject every real upload.
MAGIC = {
    ".pdf":  bytes.fromhex("255044462d"),        # %PDF-
    ".jpg":  bytes.fromhex("ffd8ff"),            # JPEG start-of-image
    ".png":  bytes.fromhex("89504e470d0a1a0a"),  # PNG signature
    ".webp": bytes.fromhex("52494646"),          # RIFF; WEBP tag checked too
}


def _looks_like(content: bytes, suffix: str) -> bool:
    """Do the actual bytes match the format the client claimed?"""
    prefix = MAGIC.get(suffix)
    if prefix is None or not content.startswith(prefix):
        return False
    # RIFF is a container; only the WEBP variant is an image we can read.
    if suffix == ".webp":
        return content[8:12] == b"WEBP"
    return True


def validate(content: bytes, content_type: str) -> str:
    """Check an upload and return the suffix to store it under."""
    suffix = ALLOWED_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if suffix is None:
        raise UploadRejected(
            "Please upload a PDF, JPG, PNG or WEBP file."
        )
    if not content:
        raise UploadRejected("That file appears to be empty.")
    # The BYTES, not the header. See MAGIC above for what this stops.
    if not _looks_like(content, suffix):
        raise UploadRejected(
            "That file does not look like the type it claims to be. Please "
            "upload a PDF, JPG, PNG or WEBP."
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
            "Please upload a smaller scan."
        )
    if suffix == ".pdf":
        try:
            pages = count_pdf_pages(content)
        except PageCountUnavailable as exc:
            # Fail CLOSED. An uncountable PDF is not a small one, and Textract
            # bills per page. Rejecting a malformed file costs the user a
            # retry; accepting it costs money we do not have.
            raise UploadRejected(
                "We could not read that PDF. Please re-save it, or upload a "
                "photo of the bill instead."
            ) from exc
        if pages > MAX_PAGES:
            raise UploadRejected(
                f"That PDF has {pages} pages; we handle up to {MAX_PAGES}."
            )
    return suffix


class PageCountUnavailable(Exception):
    """We could not count the pages. NOT the same as "the count is fine"."""


def count_pdf_pages(content: bytes) -> int:
    """Exact page count. Raises PageCountUnavailable if it cannot be had.

    Counted here, before anything billable runs, rather than discovering the
    size after paying Textract per page for it.

    USES pypdf, NOT pdfplumber, and this is the whole point. pdfplumber is
    deliberately excluded from backend/requirements.txt to keep the Lambda
    bundle small, so on Lambda the import failed, the old bare
    `except Exception: return None` swallowed it, and the caller read None as
    "no limit". The 10-page guard was therefore inert in the ONLY environment
    that bills per page -- a cost control that existed exactly where it was
    not needed. Worse than having none, because we believed in it.

    pypdf is ~1 MB, pure Python, ships in the bundle, and is exact.

    It also no longer returns None on failure. An unreadable PDF now RAISES,
    and validate() rejects it, because "we could not count the pages" must not
    silently mean "as many pages as you like".
    """
    import io

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - a packaging failure
        raise PageCountUnavailable(
            "pypdf is missing from the deployment bundle"
        ) from exc

    try:
        return len(PdfReader(io.BytesIO(content)).pages)
    except Exception as exc:
        raise PageCountUnavailable(str(exc)) from exc


#: suffix -> content type, the reverse of ALLOWED_TYPES. Lets the vision
#: reader know what it is looking at without trusting the client twice.
SUFFIX_TO_TYPE = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def put(bill_id: str, content: bytes, suffix: str) -> str:
    """Store the bytes. Returns an opaque key, never a client-supplied path."""
    # bill_id is server-generated (secrets.token_urlsafe) and the suffix comes
    # from ALLOWED_TYPES, so this key cannot be steered by the client.
    key = f"{bill_id}{suffix}"

    if config.PROVIDER == "aws":
        from . import aws_clients

        aws_clients.s3().put_object(
            Bucket=config.S3_BUCKET,
            Key=key,
            Body=content,
            ContentType=SUFFIX_TO_TYPE.get(suffix, "application/octet-stream"),
            # Objects expire via a 1-day lifecycle rule. Nothing here makes an
            # object public; the bucket blocks public access outright.
            ServerSideEncryption="AES256",
        )
        return key

    BLOB_DIR.mkdir(parents=True, exist_ok=True)
    (BLOB_DIR / key).write_bytes(content)
    return key


def get(key: str) -> bytes | None:
    """Read stored bytes back. None when the key is unknown."""
    if config.PROVIDER == "aws":
        from . import aws_clients

        try:
            return aws_clients.s3().get_object(
                Bucket=config.S3_BUCKET, Key=key
            )["Body"].read()
        except Exception:
            return None

    target = path_for(key)
    return target.read_bytes() if target else None


def content_type_for(key: str) -> str:
    return SUFFIX_TO_TYPE.get(Path(key).suffix.lower(), "application/octet-stream")


def path_for(key: str) -> Path | None:
    candidate = (BLOB_DIR / key).resolve()
    # Belt and braces: refuse anything that escaped the blob directory.
    if not str(candidate).startswith(str(BLOB_DIR.resolve())):
        return None
    return candidate if candidate.exists() else None
