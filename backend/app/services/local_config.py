"""Read user-supplied model settings without copying plaintext credentials into the repo."""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LocalModel:
    code: str
    provider_name: str
    model_name: str
    base_url: str
    kind: str
    api_key: str = field(repr=False)
    dimensions: int | None = None


def read_config(path: Path) -> list[LocalModel]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError("配置文件需要 KEY=VALUE 格式")
        values[key.strip()] = value.strip().strip("\"'")

    specs = []
    for prefix, name, kind, model_key in (
        ("DEEPSEEK", "DeepSeek", "chat", "DEEPSEEK_MODEL"),
        ("QWEN", "阿里云千问", "chat", "QWEN_MODEL"),
        ("SILICONFLOW", "硅基流动", "embedding", "EMBEDDING_MODEL"),
    ):
        for key in (f"{prefix}_API_KEY", f"{prefix}_BASE_URL", model_key):
            if not values.get(key):
                raise ValueError(f"配置缺少 {key}")
        url = values[f"{prefix}_BASE_URL"].rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.query:
            raise ValueError(f"{prefix}_BASE_URL 需要无认证信息和查询参数的 HTTP URL")
        dimensions = (
            int(values["EMBEDDING_DIM"]) if kind == "embedding" and values.get("EMBEDDING_DIM") else None
        )
        if dimensions is not None and dimensions < 1:
            raise ValueError("EMBEDDING_DIM 必须为正整数")
        specs.append(
            LocalModel(
                prefix.lower(), name, values[model_key], url, kind, values[f"{prefix}_API_KEY"], dimensions
            )
        )
    return specs


def redact_error(error: Exception, specs: list[LocalModel]) -> str:
    message = str(error)
    for spec in specs:
        message = message.replace(spec.api_key, "[REDACTED]")
    return message[:1000]
