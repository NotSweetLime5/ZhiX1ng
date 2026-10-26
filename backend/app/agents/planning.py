def ordered_steps(plan):
    pending = {s.id: s for s in plan.steps}
    if len(pending) != len(plan.steps):
        raise ValueError("计划步骤 ID 重复")
    result = []
    done = set()
    while pending:
        ready = [s for s in pending.values() if set(s.depends_on) <= done]
        if not ready:
            raise ValueError("计划依赖不存在或包含环")
        for step in ready:
            result.append(step.model_dump())
            done.add(step.id)
            del pending[step.id]
    return result


def content_text(message):
    value = message.content if hasattr(message, "content") else message
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(x if isinstance(x, str) else x.get("text", "") for x in value)
    return str(value or "")
