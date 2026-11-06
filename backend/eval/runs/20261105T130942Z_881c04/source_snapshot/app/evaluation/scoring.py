import json
import math
import re
import statistics
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    correct: bool
    grounded: bool
    note: str = Field(min_length=1, max_length=600)


def parse_judgment(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    return Judgment.model_validate_json(text, strict=True).model_dump()


def citations(answer, refs):
    # Source-shaped typos such as [R08], [D8] or [8] must not escape validation,
    # including in abstentions where a citation is optional.
    cited = set(re.findall(r"\[([A-Za-z]?\d{1,3})\]", answer))
    delivered = {r["source"] for r in refs}
    return {
        "cited": sorted(cited),
        "invalid": sorted(cited - delivered),
        "valid": not bool(cited - delivered),
        "present": bool(cited),
    }


def percentile(values, q):
    """Nearest-rank percentile; exclude missing values, retain actual zeroes."""
    values = sorted(v for v in values if v is not None)
    return values[max(0, math.ceil(q * len(values)) - 1)] if values else None


def stats(values):
    values = [v for v in values if v is not None]
    return {
        "observed": len(values),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "mean": round(statistics.mean(values), 3) if values else None,
        "sum": sum(values) if values else None,
    }


def score(case, response, judgment):
    citation = citations(response.get("answer", ""), response.get("refs", []))
    error = response.get("error") or judgment.get("error")
    passed = (
        not error
        and bool(response.get("answer", "").strip())
        and judgment.get("correct") is True
        and judgment.get("grounded") is True
        and citation["valid"]
        and (citation["present"] or not case["answerable"])
    )
    expected = set(case["expected_sources"])
    delivered = {r["source"] for r in response.get("refs", [])}
    return {
        "passed": bool(passed),
        "citation": citation,
        "expected_source_coverage": len(expected & delivered) / len(expected) if expected else None,
        "error": error,
    }


def aggregate(rows, scheduled):
    result = {
        "scheduled": scheduled,
        "recorded": len(rows),
        "status": "complete" if len(rows) == scheduled else "incomplete",
        "arms": {},
        "paired": {},
    }
    for arm in ("rag", "agentic"):
        group = [r for r in rows if r["arm"] == arm]
        passed = sum(r["score"]["passed"] for r in group)
        categories, repeats = {}, {}
        for key, target in (("category", categories), ("repeat", repeats)):
            for value in sorted({r[key] for r in group}):
                selected = [r for r in group if r[key] == value]
                target[str(value)] = {
                    "total": len(selected),
                    "passed": sum(r["score"]["passed"] for r in selected),
                }
        result["arms"][arm] = {
            "total": len(group),
            "passed": passed,
            "scheduled": scheduled // 2,
            "pass_rate": passed / (scheduled // 2) if scheduled else None,
            "response_errors": sum(bool(r.get("error")) for r in group),
            "judge_errors": sum(bool(r["judgment"].get("error")) for r in group),
            "missing_model_usage_samples": sum(bool(r.get("missing_usage_calls")) for r in group),
            "citation_invalid_samples": sum(not r["score"]["citation"]["valid"] for r in group),
            "latency_ms": stats([r.get("latency_ms") for r in group]),
            "first_answer_token_ms": stats([r.get("first_answer_token_ms") for r in group]),
            "input_tokens": stats([r.get("input_tokens") for r in group]),
            "output_tokens": stats([r.get("output_tokens") for r in group]),
            "model_calls_completed": sum(r.get("model_calls_completed", 0) for r in group),
            "additional_searches": sum(len(r.get("searches", [])) for r in group),
            "mean_expected_source_coverage": stats([r["score"]["expected_source_coverage"] for r in group])[
                "mean"
            ],
            "by_category": categories,
            "by_repeat": repeats,
        }
    pairs = {}
    for row in rows:
        pairs.setdefault((row["case_id"], row["repeat"]), {})[row["arm"]] = row
    counts = Counter()
    for pair in pairs.values():
        if set(pair) != {"rag", "agentic"} or any(r["score"]["error"] for r in pair.values()):
            counts["incomplete_or_error"] += 1
            continue
        a, b = pair["rag"]["score"]["passed"], pair["agentic"]["score"]["passed"]
        counts["both_pass" if a and b else "rag_only" if a else "agentic_only" if b else "both_fail"] += 1
    result["paired"] = dict(counts)
    result["judge_usage"] = {
        "input_tokens": stats([r["judgment"].get("input_tokens") for r in rows]),
        "output_tokens": stats([r["judgment"].get("output_tokens") for r in rows]),
    }
    result["initial_evidence_comparison"] = dict(
        Counter(
            "same"
            if sorted((r["filename"], r["content"]) for r in pair["rag"].get("initial_refs", []))
            == sorted((r["filename"], r["content"]) for r in pair["agentic"].get("initial_refs", []))
            else "different"
            for pair in pairs.values()
            if set(pair) == {"rag", "agentic"}
        )
    )
    return result


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
