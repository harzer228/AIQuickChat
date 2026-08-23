"""Extract plain text from attached documents (PDF, DOCX, plain text).

Everything here is text-only: images are handled by the vision pipeline.
"""

import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

# Plain-text documents (sent to the model as-is).
TEXT_EXTENSIONS = {
    ".txt", ".md", ".log", ".csv", ".json", ".xml", ".yml", ".yaml", ".ini",
    ".toml", ".sql", ".html", ".css", ".js", ".ts", ".py", ".java", ".c",
    ".cpp", ".h", ".sh", ".bat",
}
DOC_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}

MAX_TEXT_FILE_SIZE = 256 * 1024        # plain text / docx
MAX_PDF_FILE_SIZE = 20 * 1024 * 1024   # PDF
MAX_EXTRACT_CHARS = 80_000             # cap on the text handed to the model

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(Exception):
    """User-facing read failure; ``key`` is an i18n key, ``detail`` goes to
    the collapsible error row."""

    def __init__(self, key: str, detail: str = "", **kwargs):
        super().__init__(key)
        self.key = key
        self.detail = detail
        self.kwargs = kwargs


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
        if reader.is_encrypted:  # the empty password didn't unlock it
            raise DocumentError("chat.file_pdf_encrypted")
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for para in root.iter(_WORD_NS + "p"):
        paragraphs.append(
            "".join(node.text or "" for node in para.iter(_WORD_NS + "t")))
    return "\n".join(paragraphs)


def read_document(path: str):
    """Return ``(text, truncated)`` for a supported document.

    Raises :class:`DocumentError` for missing/oversized/undecodable files.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        size = p.stat().st_size
    except OSError as e:
        raise DocumentError("chat.error_file_read", str(e)) from None
    limit = MAX_PDF_FILE_SIZE if suffix == ".pdf" else MAX_TEXT_FILE_SIZE
    if size > limit:
        raise DocumentError(
            "chat.file_too_large", name=p.name,
            size=size // 1024, limit=limit // 1024)
    try:
        if suffix == ".pdf":
            text = _pdf_text(p)
        elif suffix == ".docx":
            text = _docx_text(p)
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
    except DocumentError:
        raise
    except Exception as e:
        raise DocumentError("chat.error_file_read", str(e)) from None
    if not text.strip():
        raise DocumentError("chat.file_empty")
    truncated = len(text) > MAX_EXTRACT_CHARS
    if truncated:
        text = text[:MAX_EXTRACT_CHARS]
    return text, truncated
