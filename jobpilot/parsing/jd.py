"""Turn a raw job description into structured requirements.

This is rule-based on purpose: it is deterministic, free, and auditable. An LLM
pass can be layered on top (see jobpilot/llm.py) to catch requirements phrased
in ways the rules miss, but the rules alone already carry the pipeline.
"""

from __future__ import annotations

import re

from ..models import Job, Necessity, Requirement
from .taxonomy import extract_domains, extract_skills, label_of, seniority_of

# Headings that switch the parser between "must have" and "nice to have".
_REQUIRED_HEAD = re.compile(
    r"^\s*(?:#+\s*)?(?:what we(?:'|’)?re looking for|requirements?|qualifications?|"
    r"must[- ]haves?|you (?:should )?have|basic qualifications|skills? (?:required|needed)|"
    r"who you are|eligibility|essential)\b", re.IGNORECASE | re.MULTILINE)
_PREFERRED_HEAD = re.compile(
    r"^\s*(?:#+\s*)?(?:nice[- ]to[- ]haves?|preferred|bonus|plus(?:es)?|good to have|"
    r"desirable|preferred qualifications|extra credit|advantage)\b",
    re.IGNORECASE | re.MULTILINE)
_NEUTRAL_HEAD = re.compile(
    r"^\s*(?:#+\s*)?(?:about (?:us|the (?:role|team|company))|responsibilities|"
    r"what you(?:'|’)?ll do|the role|benefits|perks|compensation|how to apply|"
    r"why join|our stack)\b", re.IGNORECASE | re.MULTILINE)

_PREF_INLINE = re.compile(
    r"\b(nice to have|preferred|bonus|a plus|good to have|desirable|ideally|"
    r"familiarity with|exposure to|willing(?:ness)? to learn)\b", re.IGNORECASE)

# "3+ years", "2-4 yrs of experience", "minimum 5 years building ML systems"
_YEARS = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:-|to|–)?\s*(\d+(?:\.\d+)?)?\s*\+?\s*"
    r"(?:years?|yrs?)\b(?!\s*(?:old|ago|of\s+(?:college|study|education)))", re.IGNORECASE)
_FRESHER = re.compile(r"\b(fresher|freshers|no prior experience|0[-\s]?[12]\s*years?|entry[- ]level)\b",
                      re.IGNORECASE)

_DEGREE = {
    "phd": re.compile(r"\b(ph\.?d|doctorate)\b", re.IGNORECASE),
    "masters": re.compile(r"\b(m\.?tech|m\.?s\.?c?|master'?s?|mca)\b", re.IGNORECASE),
    "bachelors": re.compile(r"\b(b\.?tech|b\.?e\b|b\.?sc|bachelor'?s?|bca|undergrad)\b", re.IGNORECASE),
}

_REMOTE = re.compile(r"\b(remote|work from home|wfh|distributed team|anywhere in india)\b", re.IGNORECASE)
_HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
_INTERN = re.compile(r"\b(intern|internship|apprentice|trainee)\b", re.IGNORECASE)
_CONTRACT = re.compile(r"\b(contract|freelance|consultant|part[- ]time)\b", re.IGNORECASE)

# Indian salary phrasings: "₹12-18 LPA", "12,00,000 - 18,00,000", "INR 25 LPA"
_LPA = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:\.\d+)?)\s*(?:-|to|–)?\s*(\d{1,3}(?:\.\d+)?)?\s*"
    r"(?:lpa|lakhs?\s*(?:per\s*annum|p\.?a\.?)?|l\s*p\s*a)", re.IGNORECASE)
_ABS_INR = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]{6,})(?:\s*(?:-|to|–)\s*(?:₹|rs\.?|inr)?\s*([\d,]{6,}))?",
                      re.IGNORECASE)

_BULLET = re.compile(r"^\s*(?:[-*•·▪]|\d+[.)])\s+")


def _sections(text: str) -> list[tuple[str, Necessity | None]]:
    """Split the JD into (chunk, necessity) where necessity may be None."""
    marks: list[tuple[int, Necessity | None]] = []
    for pattern, necessity in ((_REQUIRED_HEAD, Necessity.REQUIRED),
                               (_PREFERRED_HEAD, Necessity.PREFERRED),
                               (_NEUTRAL_HEAD, None)):
        for m in pattern.finditer(text):
            marks.append((m.start(), necessity))
    marks.sort()
    if not marks:
        return [(text, None)]
    chunks: list[tuple[str, Necessity | None]] = []
    if marks[0][0] > 0:
        chunks.append((text[: marks[0][0]], None))
    for i, (start, necessity) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        chunks.append((text[start:end], necessity))
    return chunks


def _lines(chunk: str) -> list[str]:
    out = []
    for raw in chunk.splitlines():
        line = raw.strip()
        if line:
            out.append(_BULLET.sub("", line))
    return out


def extract_requirements(text: str, title: str = "") -> list[Requirement]:
    """Canonical requirements with required/preferred classification."""
    best: dict[str, tuple[Necessity, str]] = {}

    def record(key: str, necessity: Necessity, raw: str) -> None:
        prior = best.get(key)
        if prior is None or (prior[0] is Necessity.PREFERRED and necessity is Necessity.REQUIRED):
            best[key] = (necessity, raw.strip()[:200])

    # the title itself is a strong required signal ("NLP Engineer" -> nlp)
    for key in extract_skills(title):
        record(key, Necessity.REQUIRED, title)

    for chunk, section_necessity in _sections(text):
        for line in _lines(chunk):
            inline_pref = bool(_PREF_INLINE.search(line))
            if inline_pref:
                necessity = Necessity.PREFERRED
            elif section_necessity is not None:
                necessity = section_necessity
            else:
                necessity = Necessity.PREFERRED  # unheaded prose is weak evidence
            for key in extract_skills(line):
                record(key, necessity, line)

    return [Requirement(skill=k, label=label_of(k), necessity=n, raw=raw)
            for k, (n, raw) in sorted(best.items(), key=lambda kv: kv[0])]


def extract_min_years(text: str) -> float | None:
    if _FRESHER.search(text):
        return 0.0
    m = _YEARS.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def extract_degree(text: str) -> str:
    for name in ("phd", "masters", "bachelors"):
        if _DEGREE[name].search(text):
            # "Bachelor's or Master's" should not read as a PhD requirement
            if name == "phd" and re.search(r"\b(ph\.?d|doctorate)\b.{0,40}\b(preferred|plus|bonus)\b",
                                           text, re.IGNORECASE | re.DOTALL):
                continue
            return name
    return ""


def extract_salary(text: str) -> tuple[str, float | None, float | None]:
    """Return (raw text, min LPA, max LPA). Absolute rupee figures are converted."""
    m = _LPA.search(text)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else None
        return m.group(0).strip(), lo, hi
    m = _ABS_INR.search(text)
    if m:
        def lpa(v: str | None) -> float | None:
            if not v:
                return None
            n = float(v.replace(",", ""))
            return round(n / 100000.0, 2) if n >= 100000 else None
        lo, hi = lpa(m.group(1)), lpa(m.group(2))
        if lo:
            return m.group(0).strip(), lo, hi
    return "", None, None


def detect_employment_type(title: str, text: str) -> str:
    blob = f"{title}\n{text[:1500]}"
    if _INTERN.search(blob):
        return "internship"
    if _CONTRACT.search(blob):
        return "contract"
    return "full_time"


def detect_remote(location: str, text: str) -> bool:
    blob = f"{location}\n{text[:2000]}"
    return bool(_REMOTE.search(blob)) and not _HYBRID.search(blob)


def enrich(job: Job) -> Job:
    """Fill in the parsed fields of a Job in place and return it."""
    text = job.description or ""
    job.requirements = extract_requirements(text, job.title)
    job.min_years = extract_min_years(text)
    job.degree_required = extract_degree(text)
    job.seniority = seniority_of(job.title)
    job.employment_type = detect_employment_type(job.title, text)
    if not job.remote:
        job.remote = detect_remote(job.location, text)
    if not job.salary_text:
        job.salary_text, job.salary_min_lpa, job.salary_max_lpa = extract_salary(text)
    return job


def job_domains(job: Job, company_about: str = "") -> dict[str, int]:
    return extract_domains(f"{job.title}\n{job.description}\n{company_about}")
