"""Load local documents into chat context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MAX_DOCUMENT_CHARS = 60_000
IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass(frozen=True)
class LoadedDocument:
    path: Path
    content: str
    truncated: bool = False


class DocumentLoadError(Exception):
    """Raised when a document cannot be loaded as text."""


def load_document(path_text: str, *, max_chars: int = MAX_DOCUMENT_CHARS) -> LoadedDocument:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise DocumentLoadError(f"File tidak ditemukan: {path}")
    if not path.is_file():
        raise DocumentLoadError(f"Path bukan file: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        content = _read_pdf(path)
    elif suffix == ".docx":
        content = _read_docx(path)
    elif suffix in IMAGE_EXTENSIONS:
        content = _read_image(path)
    else:
        content = _read_text(path, max_chars=max_chars + 1)

    content = content.strip()
    if not content:
        raise DocumentLoadError(f"File kosong atau tidak berisi teks yang bisa dibaca: {path}")

    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars].rstrip()

    return LoadedDocument(path=path, content=content, truncated=truncated)


def build_document_prompt(document: LoadedDocument, question: str | None = None) -> str:
    suffix = "\n\n[Catatan: isi file dipotong karena terlalu panjang.]" if document.truncated else ""
    instruction = question.strip() if question and question.strip() else "Tolong ringkas isi dokumen ini."
    return (
        f"Saya melampirkan isi file `{document.path}`.\n\n"
        f"```text\n{document.content}\n```"
        f"{suffix}\n\n"
        f"Pertanyaan/instruksi saya: {instruction}"
    )


def _read_text(path: Path, *, max_chars: int) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise DocumentLoadError(
            f"File terlihat seperti binary dan tidak bisa dibaca sebagai teks: {path}"
        )

    data = raw[: max_chars * 4]
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentLoadError(f"Gagal decode file teks: {path}")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            raise DocumentLoadError(
                "Membaca PDF butuh paket tambahan. Install salah satu: "
                "`pip install pypdf` atau `pip install PyPDF2`."
            ) from exc

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n\n".join(pages).strip()
    if not text:
        raise DocumentLoadError(
            "PDF tidak berisi teks yang bisa diekstrak. Jika ini PDF hasil scan, "
            "ubah halaman menjadi gambar lalu pakai `/file gambar.png ...`, atau "
            "jalankan OCR PDF di luar aplikasi terlebih dahulu."
        )
    return text


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise DocumentLoadError(
            "Membaca DOCX butuh paket tambahan: `pip install python-docx`."
        ) from exc

    doc = Document(str(path))
    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def _read_image(path: Path) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise DocumentLoadError(
            "Membaca gambar butuh paket tambahan: `pip install Pillow pytesseract`."
        ) from exc

    try:
        import pytesseract
    except ImportError as exc:
        raise DocumentLoadError(
            "Membaca teks dari gambar butuh OCR: `pip install pytesseract` "
            "dan install aplikasi Tesseract di sistem."
        ) from exc

    try:
        image = Image.open(path)
    except OSError as exc:
        raise DocumentLoadError(f"Gagal membuka gambar: {path}") from exc

    try:
        text = pytesseract.image_to_string(image, lang="ind+eng")
    except pytesseract.TesseractNotFoundError as exc:
        raise DocumentLoadError(
            "Aplikasi Tesseract belum ditemukan. Install dulu, misalnya: "
            "`sudo apt install tesseract-ocr tesseract-ocr-ind`."
        ) from exc
    except pytesseract.TesseractError:
        text = pytesseract.image_to_string(image)

    text = text.strip()
    if not text:
        raise DocumentLoadError(
            "Tidak ada teks yang terdeteksi di gambar. Pastikan gambar cukup jelas "
            "atau gunakan gambar dengan resolusi lebih tinggi."
        )
    return text
