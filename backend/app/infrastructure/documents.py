import io
import re
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document as WordDocument
from langchain_core.documents import Document
from pypdf import PdfReader


def load_document(filename, data):
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return load_pdf(data)
    if ext == ".docx":
        doc = WordDocument(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs)
        text += "\n" + "\n".join(" | ".join(c.text for c in r.cells) for tb in doc.tables for r in tb.rows)
    elif ext in {".txt", ".md", ".markdown", ".html", ".htm"}:
        text = data.decode("utf-8-sig")
        if ext in {".html", ".htm"}:
            text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
    else:
        raise ValueError("支持 PDF、DOCX、TXT、Markdown 和 HTML")
    return [Document(page_content=text, metadata={"page": 1})]


def load_pdf(data):
    reader = PdfReader(io.BytesIO(data))
    documents = []
    scanned = []
    for index, page in enumerate(reader.pages):
        text = normalize_pdf_text(page.extract_text() or "")
        documents.append(Document(page_content=text, metadata={"page": index + 1}))
        if len(re.sub(r"\s+", "", text)) < 40 and page.images:
            scanned.append(index)
    if scanned:
        from app.infrastructure.pdf_ocr import recognize_pages

        for index, text in recognize_pages(data, scanned).items():
            text = normalize_pdf_text(text)
            if len(text.strip()) > len(documents[index].page_content.strip()):
                documents[index].page_content = text
                documents[index].metadata["ocr"] = True
    return documents


def normalize_pdf_text(text: str) -> str:
    """Recover PDF UTF-16 surrogate pairs; replace invalid halves before UTF-8 storage."""
    return (
        text.encode("utf-16-le", errors="surrogatepass")
        .decode("utf-16-le", errors="replace")
        .replace("\x00", "")
    )
