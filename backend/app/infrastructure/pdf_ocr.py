"""Local Chinese/English OCR for PDF pages that only contain rasterized text."""

from functools import lru_cache
from threading import Lock

_lock = Lock()


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def recognize_pages(data: bytes, indices: list[int]) -> dict[int, str]:
    import pypdfium2 as pdfium

    result = {}
    with _lock, pdfium.PdfDocument(data) as pdf:
        engine = ocr_engine()
        for index in indices:
            page = pdf[index]
            bitmap = None
            try:
                width, height = page.get_size()
                scale = min(2.5, 2800 / max(width, height))
                bitmap = page.render(scale=scale)
                lines, _ = engine(bitmap.to_numpy())
                result[index] = "\n".join(line[1] for line in lines or [])
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()
    return result
