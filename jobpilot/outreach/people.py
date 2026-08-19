"""Finding the right human, honestly.

What this module does NOT do: scrape LinkedIn, buy contact databases, or write a
guessed address into a field that later reads as if it were verified.

What it does:
  * keeps a `people.yaml` you curate, with a source and a confidence per record;
  * tells you which kind of person to approach for a given opportunity;
  * generates the exact public searches to run to find that person;
  * produces email *candidates* from a company domain, permanently labelled
    `pattern_guess`, so nothing can silently treat them as verified;
  * falls back to the generic careers inbox, which is always fair game.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus, urlparse

from ..models import Company, Job, Mode, Person

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

# Who to aim for, best first, per outreach mode.
TARGETS: dict[Mode, list[str]] = {
    Mode.DIRECT: ["recruiter", "talent_acquisition", "hiring_manager", "ml_lead", "engineering_manager"],
    Mode.RECRUITER: ["recruiter", "talent_acquisition", "hiring_manager", "engineering_manager"],
    Mode.FOUNDER: ["founder", "cto", "ml_lead", "engineering_manager"],
    Mode.TECHNICAL: ["ml_lead", "research_lead", "cto", "engineering_manager", "hiring_manager"],
}

ROLE_TITLES: dict[str, list[str]] = {
    "recruiter": ["recruiter", "technical recruiter", "talent acquisition"],
    "talent_acquisition": ["talent acquisition", "head of talent", "people operations"],
    "hiring_manager": ["engineering manager", "hiring manager", "team lead"],
    "ml_lead": ["ml lead", "head of machine learning", "ai lead", "principal scientist",
                "research engineer", "member of technical staff"],
    "research_lead": ["research lead", "head of research", "principal researcher"],
    "engineering_manager": ["engineering manager", "director of engineering"],
    "founder": ["founder", "co-founder", "ceo"],
    "cto": ["cto", "chief technology officer", "vp engineering"],
}

GENERIC_LOCALPARTS = ["careers", "jobs", "hiring", "hr", "talent", "hello", "contact", "info"]


def load_people(path: str | Path) -> dict[str, Person]:
    """Read your curated contact file. Shape:

    people:
      - key: nanonets_recruiter
        company: nanonets
        name: A. Person
        title: Technical Recruiter
        role_class: recruiter
        linkedin: https://...
        email: a.person@example.com
        email_status: published     # verified | published | pattern_guess | unknown
        source: "company careers page, 2026-08-01"
    """
    path = Path(path)
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required to read people files")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("people", data if isinstance(data, list) else [])
    out: dict[str, Person] = {}
    for raw in entries or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        company_key = str(raw.get("company") or raw.get("company_key") or "").strip()
        key = str(raw.get("key") or f"{company_key}_{name.lower().replace(' ', '_')}")
        status = str(raw.get("email_status", "unknown")).lower()
        confidence = raw.get("email_confidence")
        if confidence is None:
            confidence = {"verified": 1.0, "published": 0.85, "pattern_guess": 0.25}.get(status, 0.0)
        out[key] = Person(
            key=key,
            company_key=company_key,
            name=name,
            title=str(raw.get("title", "")),
            role_class=str(raw.get("role_class", "")),
            linkedin=str(raw.get("linkedin", "")),
            email=str(raw.get("email", "")),
            email_status=status,
            email_confidence=float(confidence),
            source=str(raw.get("source", "people.yaml")),
            notes=str(raw.get("notes", "")),
        )
    return out


def domain_of(company: Company) -> str:
    url = company.website or company.careers_url
    if not url:
        return ""
    host = urlparse(url if "://" in url else f"https://{url}").netloc
    return host[4:] if host.startswith("www.") else host


def generic_inboxes(company: Company) -> list[Person]:
    """careers@/jobs@ style addresses: still guesses, but low-risk ones."""
    domain = domain_of(company)
    if not domain:
        return []
    out = []
    for local in GENERIC_LOCALPARTS[:4]:
        out.append(Person(
            key=f"{company.key}_{local}",
            company_key=company.key,
            name=f"{company.name} {local} inbox",
            title="Generic inbox",
            role_class="inbox",
            email=f"{local}@{domain}",
            email_status="pattern_guess",
            email_confidence=0.3,
            source=f"constructed from {domain}",
            notes="verify on the company's contact/careers page before sending",
        ))
    return out


def guess_email_candidates(full_name: str, company: Company) -> list[str]:
    """Common corporate patterns. Always a guess - never store as verified."""
    domain = domain_of(company)
    parts = [p for p in (full_name or "").lower().replace(".", " ").split() if p.isalpha()]
    if not domain or not parts:
        return []
    first, last = parts[0], parts[-1] if len(parts) > 1 else ""
    patterns = [f"{first}", f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}",
                f"{first}_{last}", f"{last}.{first}"]
    seen, out = set(), []
    for local in patterns:
        local = local.strip("._")
        if local and local not in seen:
            seen.add(local)
            out.append(f"{local}@{domain}")
    return out


def search_queries(company: Company, job: Job | None, mode: Mode) -> list[str]:
    """Public searches that actually find the right person. Run these yourself."""
    name = company.name
    queries = []
    for role_class in TARGETS.get(mode, [])[:3]:
        titles = ROLE_TITLES.get(role_class, [role_class])
        titles_or = " OR ".join(f'"{t}"' for t in titles[:3])
        queries.append(f'site:linkedin.com/in "{name}" ({titles_or})')
    if job:
        queries.append(f'"{name}" "{job.title}" (recruiter OR "hiring manager")')
    domain = domain_of(company)
    if domain:
        queries.append(f'site:{domain} (careers OR jobs OR "join us" OR team)')
        queries.append(f'"@{domain}" (careers OR hiring OR recruitment)')
    queries.append(f'"{name}" team page OR "about us" OR "our team"')
    return queries


def search_urls(queries: Iterable[str]) -> list[str]:
    return [f"https://www.google.com/search?q={quote_plus(q)}" for q in queries]


def contact_plan(company: Company, job: Job | None, mode: Mode,
                 known: dict[str, Person] | None = None) -> dict[str, object]:
    """Everything you need to get to a human, ranked."""
    known = known or {}
    mine = [p for p in known.values() if p.company_key == company.key]
    order = TARGETS.get(mode, [])
    mine.sort(key=lambda p: (order.index(p.role_class) if p.role_class in order else 99,
                             -p.email_confidence))
    queries = search_queries(company, job, mode)
    return {
        "mode": mode.value,
        "target_roles": order,
        "known_contacts": mine,
        "best_contact": mine[0] if mine else None,
        "generic_inboxes": generic_inboxes(company),
        "searches": queries,
        "search_urls": search_urls(queries),
        "founders": company.founders,
    }
