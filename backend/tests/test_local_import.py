import io

import pytest
from PIL import Image

from app import models as t
from app.core.config import Settings
from app.infrastructure.documents import load_document, normalize_pdf_text
from app.services.llm import Descriptor, Gateway
from app.services.local_config import read_config, redact_error
from app.services.local_import import import_document, save_default_aliases


def config_text():
    return """DEEPSEEK_API_KEY=unit-secret-deepseek
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
QWEN_API_KEY = 'unit-secret-qwen'
QWEN_MODEL=qwen-unit
QWEN_BASE_URL=https://example.invalid/v1
SILICONFLOW_API_KEY=unit-secret-embedding
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
EMBEDDING_DIM=2560
"""


def test_local_configuration_and_credentials_are_not_logged(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text(config_text(), encoding="utf-8-sig")
    specs = read_config(path)
    assert specs[1].api_key == "unit-secret-qwen"
    assert specs[2].dimensions == 2560
    assert "unit-secret" not in repr(specs)
    error = ValueError("unit-secret-deepseek unit-secret-qwen unit-secret-embedding")
    assert "unit-secret" not in redact_error(error, specs)
    path.write_text(config_text().replace("https://api.deepseek.com", "https://api.deepseek.com?key=bad"))
    with pytest.raises(ValueError, match="BASE_URL"):
        read_config(path)


def test_changing_defaults_preserves_existing_secrets(tmp_path):
    config = tmp_path / "config.txt"
    config.write_text(config_text())
    env = tmp_path / ".env"
    env.write_text("ZHIXING_JWT_SECRET=existing-jwt\nZHIXING_SECRET_KEY=existing-encryption\nZHIXING_DEFAULT_CHAT=old\n")
    save_default_aliases(read_config(config), env)
    saved = env.read_text()
    assert "ZHIXING_JWT_SECRET=existing-jwt" in saved and "ZHIXING_SECRET_KEY=existing-encryption" in saved
    assert "ZHIXING_DEFAULT_CHAT=deepseek-flash" in saved
    assert "ZHIXING_DEFAULT_EMBEDDING=Qwen/Qwen3-Embedding-4B" in saved
    assert "unit-secret" not in saved


def test_scanned_pdf_uses_ocr_and_keeps_page_metadata(monkeypatch):
    from app.infrastructure import pdf_ocr

    text = "This scanned page contains important knowledge for retrieval."
    calls = []

    def recognize(data, indices):
        calls.append(indices)
        return {0: text}

    monkeypatch.setattr(pdf_ocr, "recognize_pages", recognize)
    pdf = io.BytesIO()
    Image.new("RGB", (320, 200), color="white").save(pdf, format="PDF")
    documents = load_document("scanned.pdf", pdf.getvalue())
    assert calls == [[0]]
    assert documents[0].page_content == text
    assert documents[0].metadata == {"page": 1, "ocr": True}


def test_gateway_sets_native_sampling_parameters():
    gateway = Gateway(None, None, Settings())
    model = gateway.chat(
        Descriptor(
            {"model_name": "test", "max_output": 512},
            {"base_url": "http://example.invalid/v1"},
            "unit-secret",
        ),
        {"top_p": 0.8, "temperature": 0.2},
    )
    assert model.top_p == 0.8 and model.temperature == 0.2
    assert "top_p" not in model.model_kwargs


def test_pdf_surrogates_are_recovered_for_utf8_and_postgres():
    text = normalize_pdf_text("正常中文\ud83d\ude00，异常字符\ud83d\x00结束")
    assert text == "正常中文😀，异常字符�结束"
    text.encode("utf-8")


async def test_document_import_skips_duplicates_and_retries_failed_jobs(rt, client, tmp_path):
    response = await client.post(
        "/api/v1/kbs", json={"name": "本机导入测试", "embedding_config_id": rt.test_embed["id"]}
    )
    assert response.status_code == 200
    kb = response.json()["data"]
    path = tmp_path / "paper.txt"
    path.write_text("A document for testing import deduplication.", encoding="utf-8")
    first, created = await import_document(rt, rt.test_user, kb, path)
    assert created
    second, created = await import_document(rt, rt.test_user, kb, path)
    assert not created and first["id"] == second["id"]
    assert len(await rt.db.rows(t.documents, t.documents.c.kb_id == kb["id"])) == 1
    assert (await rt.db.get(t.kbs, kb["id"]))["doc_count"] == 1
    jobs = await rt.db.rows(
        t.jobs, t.jobs.c.kind == "doc_etl", t.jobs.c.payload["doc_id"].as_integer() == first["id"]
    )
    await rt.db.change(t.jobs, jobs[0]["id"], {"status": "failed", "attempts": 3, "error": "previous error"})
    await rt.db.change(t.documents, first["id"], {"status": "failed"})
    resumed, created = await import_document(rt, rt.test_user, kb, path)
    assert not created and resumed["id"] == first["id"]
    job = await rt.db.get(t.jobs, jobs[0]["id"])
    assert job["status"] == "pending" and job["attempts"] == 0 and job["error"] == ""
