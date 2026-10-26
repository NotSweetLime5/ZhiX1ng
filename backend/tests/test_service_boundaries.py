"""Regression coverage for typed CRUD and service-to-HTTP error translation."""

import ast
import uuid
from pathlib import Path

from app import models as t
from app.main import app


def test_services_do_not_import_http_routes():
    root = Path(__file__).parents[1] / "app"
    for path in (root / "services").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("fastapi", "app.api")), path.name
            elif isinstance(node, ast.Import):
                assert not any(n.name.startswith(("fastapi", "app.api")) for n in node.names), path.name

    schemas = app.openapi()["components"]["schemas"]
    assert {"AgentInput", "ProviderInput", "ModelInput", "MCPServerInput", "DatasetInput"} <= schemas.keys()


async def test_typed_catalog_preserves_encryption_partial_updates_and_reference_guards(rt, client):
    code = "schema_" + uuid.uuid4().hex[:12]
    secret = "test-provider-key-1234"
    created = await client.post(
        "/api/v1/admin/models/providers",
        json={"code": code, "name": "Test Provider", "base_url": "http://test.invalid/v1", "api_key": secret},
    )
    assert created.status_code == 200, created.text
    provider = created.json()["data"]
    ident = provider["id"]
    assert "api_key" not in provider and secret not in created.text
    try:
        stored = await rt.db.get(t.providers, ident)
        encrypted = stored["api_key"]
        assert encrypted != secret and rt.security.decrypt(encrypted) == secret

        updated = await client.put(
            f"/api/v1/admin/models/providers/{ident}", json={"name": "Renamed", "api_key": ""}
        )
        assert updated.status_code == 200, updated.text
        stored = await rt.db.get(t.providers, ident)
        assert stored["name"] == "Renamed" and stored["api_key"] == encrypted
        assert stored["base_url"] == "http://test.invalid/v1"

        unknown = await client.put(f"/api/v1/admin/models/providers/{ident}", json={"unexpected": 1})
        assert unknown.status_code == 422 and unknown.json()["code"] == 422

        invalid = await client.post(
            "/api/v1/admin/models",
            json={"provider_id": ident, "model_name": "test", "alias": code, "type": "invalid"},
        )
        assert invalid.status_code == 422
        created_model = await client.post(
            "/api/v1/admin/models",
            json={"provider_id": ident, "model_name": "test", "alias": code, "type": "chat"},
        )
        assert created_model.status_code == 200, created_model.text
        model_id = created_model.json()["data"]["id"]
        blocked = await client.delete(f"/api/v1/admin/models/providers/{ident}")
        assert blocked.status_code == 409 and blocked.json()["code"] == 409
        assert (await client.delete(f"/api/v1/admin/models/{model_id}")).status_code == 200
        assert (await client.delete(f"/api/v1/admin/models/providers/{ident}")).status_code == 200
        missing = await client.put(f"/api/v1/admin/models/providers/{ident}", json={"name": "Missing"})
        assert missing.status_code == 404 and missing.json()["code"] == 404
    finally:
        await rt.db.remove(t.providers, ident)
