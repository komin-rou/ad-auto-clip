"""Fact-grounded single-location advertisement copy generation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from location_loader import Location


class ScriptValidationError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("；".join(issues))


@dataclass(frozen=True)
class FactLibrary:
    required_phrases: tuple[str, ...]
    forbidden_claims: tuple[str, ...] = ()
    forbidden_number_pattern: bool = True
    target_chars: int = 110

    @classmethod
    def from_file(cls, path: str | Path) -> "FactLibrary":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(
            required_phrases=tuple(str(x).strip() for x in data.get("required_phrases", []) if str(x).strip()),
            forbidden_claims=tuple(str(x).strip() for x in data.get("forbidden_claims", []) if str(x).strip()),
            forbidden_number_pattern=bool(data.get("reject_unknown_numbers", True)),
            target_chars=int(data.get("target_chars", 110)),
        )


@dataclass(frozen=True)
class AdScript:
    text: str
    source: str
    attempts: int


def build_local_script(location: Location, facts: FactLibrary) -> str:
    facts_text = "，".join(facts.required_phrases)
    return (
        f"在{location.full_name}，师傅正在上门了解雨棚安装需求。"
        f"我们提供{facts_text}。方案确认好后，就可以安心等待施工安排。"
    )


def _number_tokens(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    pattern = r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万两]+)(?:年|天|小时|分钟|秒|平方米|平|D)?"
    return set(re.findall(pattern, compact, flags=re.IGNORECASE))


def validate_ad_script(text: str, location: Location, facts: FactLibrary) -> None:
    issues = []
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        issues.append("文案为空")
    if location.full_name not in normalized and location.spoken_name not in normalized:
        issues.append(f"文案缺少地点：{location.full_name}")
    for phrase in facts.required_phrases:
        if re.sub(r"\s+", "", phrase) not in normalized:
            issues.append(f"文案缺少事实：{phrase}")
    for claim in facts.forbidden_claims:
        if claim in normalized:
            issues.append(f"文案包含禁止声明：{claim}")
    if facts.forbidden_number_pattern:
        allowed_source = "".join(facts.required_phrases) + location.full_name
        allowed = _number_tokens(allowed_source)
        unknown = sorted(token for token in _number_tokens(normalized) if token not in allowed)
        if unknown:
            issues.append(f"文案包含事实库外的数字：{'、'.join(unknown)}")
    if issues:
        raise ScriptValidationError(issues)


def _deepseek_generate(location: Location, facts: FactLibrary, config) -> str:
    import requests

    facts_json = json.dumps(list(facts.required_phrases), ensure_ascii=False)
    prompt = (
        f"为地点“{location.full_name}”写一段约{facts.target_chars}字的雨棚短视频口播。"
        f"只能使用这些事实：{facts_json}。必须包含完整地点和每条事实，不得加入价格、工期、质保、排名或其他数字。只输出正文。"
    )
    response = requests.post(
        f"{config.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json={"model": config.DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.8},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def generate_ad_script(
    location: Location,
    facts: FactLibrary,
    config,
    supplied_text: str | None = None,
    generator: Callable[[Location, FactLibrary, object], str] | None = None,
) -> AdScript:
    if supplied_text:
        validate_ad_script(supplied_text, location, facts)
        return AdScript(supplied_text.strip(), "provided", 1)
    if not getattr(config, "DEEPSEEK_API_KEY", ""):
        text = build_local_script(location, facts)
        validate_ad_script(text, location, facts)
        return AdScript(text, "local", 1)
    generate = generator or _deepseek_generate
    last_error = None
    for attempt in range(1, int(getattr(config, "COPY_MAX_RETRIES", 3)) + 1):
        text = generate(location, facts, config)
        try:
            validate_ad_script(text, location, facts)
            return AdScript(text, "deepseek", attempt)
        except ScriptValidationError as exc:
            last_error = exc
    raise ScriptValidationError([f"文案重试后仍不合格：{last_error}"])
