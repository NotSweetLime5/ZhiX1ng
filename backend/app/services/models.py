from app import models as t


async def chat_models(rt, user):
    rows = await rt.db.rows(t.models, t.models.c.type == "chat", t.models.c.status == 1)
    result = []
    for model in rows:
        provider = await rt.db.get(t.providers, model["provider_id"])
        if provider and provider["status"] == 1:
            result.append(
                {
                    "id": model["id"],
                    "label": model["alias"] or model["model_name"],
                    "model_name": model["model_name"],
                    "provider": provider["name"],
                    "is_default": model["is_default"],
                }
            )
    return result
