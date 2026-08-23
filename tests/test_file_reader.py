"""file_reader: PDF / DOCX / plain-text extraction with limits."""

import io
import zipfile

import pytest

from utils.file_reader import (
    MAX_EXTRACT_CHARS,
    MAX_TEXT_FILE_SIZE,
    DocumentError,
    read_document,
)


def _make_pdf(text: str) -> bytes:
    """Build a minimal valid single-page PDF containing ``text``."""
    content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
         b"/Resources << /Font << /F1 5 0 R >> >> >>"),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(b"xref\n0 " + str(len(objects) + 1).encode("ascii") + b"\n")
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.write((f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
               f"startxref\n{xref_at}\n%%EOF").encode("ascii"))
    return out.getvalue()


def _make_docx(text: str) -> bytes:
    word_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraph = "".join(
        f"<w:p xmlns:w=\"{word_ns}\"><w:r><w:t>{part}</w:t></w:r></w:p>"
        for part in text.split("\n"))
    document = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<w:document xmlns:w="{word_ns}"><w:body>{paragraph}</w:body></w:document>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_read_plain_text(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hello файл", encoding="utf-8")
    text, truncated = read_document(str(p))
    assert text == "hello файл"
    assert truncated is False


def test_read_pdf(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(_make_pdf("Hello PDF"))
    text, truncated = read_document(str(p))
    assert "Hello PDF" in text
    assert truncated is False


def test_read_encrypted_pdf(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    src = pypdf.PdfReader(io.BytesIO(_make_pdf("secret")))
    writer = pypdf.PdfWriter()
    writer.append(src)
    writer.encrypt("пароль")
    p = tmp_path / "locked.pdf"
    with open(p, "wb") as fh:
        writer.write(fh)
    with pytest.raises(DocumentError) as err:
        read_document(str(p))
    assert err.value.key == "chat.file_pdf_encrypted"


def test_read_docx(tmp_path):
    p = tmp_path / "doc.docx"
    p.write_bytes(_make_docx("первая строка\nвторая строка"))
    text, truncated = read_document(str(p))
    assert "первая строка" in text
    assert "вторая строка" in text
    assert truncated is False


def test_oversized_text_file(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * (MAX_TEXT_FILE_SIZE + 1024), encoding="utf-8")
    with pytest.raises(DocumentError) as err:
        read_document(str(p))
    assert err.value.key == "chat.file_too_large"


def test_empty_file(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("   ", encoding="utf-8")
    with pytest.raises(DocumentError) as err:
        read_document(str(p))
    assert err.value.key == "chat.file_empty"


def test_broken_pdf(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4 this is not a real pdf at all")
    with pytest.raises(DocumentError) as err:
        read_document(str(p))
    assert err.value.key == "chat.error_file_read"


def test_long_text_truncated(tmp_path):
    p = tmp_path / "long.txt"
    p.write_text("a" * (MAX_EXTRACT_CHARS + 5000), encoding="utf-8")
    text, truncated = read_document(str(p))
    assert truncated is True
    assert len(text) == MAX_EXTRACT_CHARS
