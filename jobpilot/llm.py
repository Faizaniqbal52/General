"""Optional LLM layer.

The rule-based pipeline works with no API key at all - that is the default and
the tests only exercise that path. When a key is present, an LLM can do two
narrow jobs it is genuinely better at than regexes:

  1. spot requirements phrased in ways the taxonomy misses
     ("you should be comfortable owning a model from data to production");
  2. tighten the wording of a draft email.

Both are deliberately constrained. Requirement extraction is forced to return
keys that already exist in the taxonomy, so the model cannot invent a skill.
Email polishing is checked afterwards: if the rewrite introduces a number, a
URL or an email address that was not in the original, it is rejected and the
original text is kept. The LLM is allowed to improve the phrasing of your
claims; it is not allowed to add claims.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

from .models import Job, Necessity, Requirement
from .parsing.taxonomy import SKILLS, label_of

MODEL = "claude-opus-5"

_REQUIREMENTS_SYSTEM = """You extract structured requirements from job descriptions.

You will be given a job title, the description, and a fixed vocabulary of skill
keys. Return ONLY the requirements that the description genuinely implies, using
keys from the vocabulary. Never invent a key that is not in the vocabulary.
Prefer precision over recall: if a requirement is not clearly stated, leave it out.

Respond with JSON only, in this exact shape:
{"requirements": [{"skill": "<vocabulary key>", "necessity": "required" | "preferred",
                   "evidence": "<short quote from the description>"}]}"""

_EMAIL_SYSTEM = """You are copy-editing a job-application email that the sender wrote
about their own work.

Rules, in order of importance:
1. Do not add any fact, claim, number, link, employer, or credential that is not
   already in the draft. If something is not there, it does not go in.
2. Do not remove the concrete project details - they are the point of the email.
3. Make it read like a person wrote it: shorter sentences, no corporate filler,
   no "I am writing to express my interest", no flattery.
4. Keep it under 200 words and keep the sender's sign-off.

Return the edited email body only, as plain text."""

_NUMBER = re.compile(r"\d[\d,.]*")
_URLISH = re.compile(r"(?:https?://\S+|\b[\w.+-]+@[\w-]+\.[\w.]+)")


class Enricher(Protocol):
    """What the rest of the codebase is allowed to ask an LLM for."""

    available: bool

    def extend_requirements(self, job: Job) -> list[Requirement]: ...

    def polish_email(self, body: str) -> str: ...


@dataclass
class NullEnricher:
    """The default: does nothing, costs nothing, never fails."""

    available: bool = False

    def extend_requirements(self, job: Job) -> list[Requirement]:
        return list(job.requirements)

    def polish_email(self, body: str) -> str:
        return body


class ClaudeEnricher:
    """Uses the Anthropic API when a key is configured."""

    available = True

    def __init__(self, model: str = MODEL, client: object | None = None):
        self.model = model
        if client is not None:
            self.client = client
        else:
            import anthropic  # imported lazily so the package stays dependency-free
            self.client = anthropic.Anthropic()

    # -- internals -------------------------------------------------------
    def _ask(self, system: str, prompt: str, max_tokens: int = 2000) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content
                       if getattr(block, "type", "") == "text").strip()

    # -- public ----------------------------------------------------------
    def extend_requirements(self, job: Job) -> list[Requirement]:
        vocabulary = ", ".join(sorted(SKILLS))
        prompt = (f"Job title: {job.title}\n"
                  f"Company: {job.company_name}\n\n"
                  f"Description:\n{job.description[:12000]}\n\n"
                  f"Vocabulary: {vocabulary}")
        try:
            raw = self._ask(_REQUIREMENTS_SYSTEM, prompt)
            payload = json.loads(_json_slice(raw))
        except Exception:  # noqa: BLE001 - the rule-based result is always a valid fallback
            return list(job.requirements)

        existing = {r.skill for r in job.requirements}
        merged = list(job.requirements)
        for item in payload.get("requirements", []):
            key = str(item.get("skill", "")).strip().lower()
            if key not in SKILLS or key in existing:
                continue
            necessity = (Necessity.REQUIRED if str(item.get("necessity")) == "required"
                         else Necessity.PREFERRED)
            merged.append(Requirement(skill=key, label=label_of(key), necessity=necessity,
                                      raw=str(item.get("evidence", ""))[:200]))
            existing.add(key)
        return merged

    def polish_email(self, body: str) -> str:
        try:
            edited = self._ask(_EMAIL_SYSTEM, body, max_tokens=1200)
        except Exception:  # noqa: BLE001
            return body
        return edited if _keeps_the_facts(body, edited) else body


def _json_slice(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else text


def _keeps_the_facts(original: str, edited: str) -> bool:
    """Reject a rewrite that introduced numbers, links or addresses of its own."""
    if not edited or len(edited) > len(original) * 1.6:
        return False
    for pattern in (_NUMBER, _URLISH):
        if set(pattern.findall(edited)) - set(pattern.findall(original)):
            return False
    return True


def from_env(enabled: bool = True) -> Enricher:
    """A Claude-backed enricher when a key is configured, otherwise the null one."""
    if not enabled:
        return NullEnricher()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not has_key:
        return NullEnricher()
    try:
        return ClaudeEnricher()
    except Exception:  # noqa: BLE001 - missing SDK, bad credentials, anything
        return NullEnricher()
