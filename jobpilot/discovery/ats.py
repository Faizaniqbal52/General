"""Connectors for the public job-board APIs that ATS vendors publish.

Greenhouse, Lever, Ashby, Workable and Recruitee all expose a company's open
roles as JSON specifically so that job aggregators can read them. That makes
them the right primary source: stable, structured, and nobody's terms are being
bent to read them. LinkedIn/Indeed scraping is deliberately not implemented -
see `jobpilot/discovery/search.py` for the supported way to bring in listings
found elsewhere.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from ..models import Company, Job
from ..net import Client, FetchError
from ..textutil import strip_html


def _job(company: Company, title: str, url: str, location: str, description: str,
         source: str, posted_at: str = "", remote: bool = False,
         employment_type: str = "full_time", salary_text: str = "") -> Job:
    return Job(
        id=Job.make_id(company.key, title, url, location),
        company_key=company.key,
        company_name=company.name,
        title=(title or "").strip(),
        url=url or company.careers_url,
        location=(location or "").strip(),
        remote=remote,
        description=description or "",
        employment_type=employment_type,
        salary_text=salary_text,
        posted_at=(posted_at or "")[:10],
        source=source,
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value)


# --------------------------------------------------------------------------
# Greenhouse
# --------------------------------------------------------------------------

def greenhouse(client: Client, company: Company, slug: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = client.get_json(url)
    jobs = []
    for item in data.get("jobs", []) or []:
        offices = item.get("offices") or []
        location = _text((item.get("location") or {}).get("name")) or ", ".join(
            _text(o.get("name")) for o in offices)
        jobs.append(_job(
            company,
            title=_text(item.get("title")),
            url=_text(item.get("absolute_url")),
            location=location,
            description=strip_html(_text(item.get("content"))),
            source="greenhouse",
            posted_at=_text(item.get("updated_at") or item.get("first_published")),
        ))
    return jobs


# --------------------------------------------------------------------------
# Lever
# --------------------------------------------------------------------------

def lever(client: Client, company: Company, slug: str) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = client.get_json(url)
    jobs = []
    for item in data if isinstance(data, list) else []:
        categories = item.get("categories") or {}
        body = item.get("descriptionPlain") or strip_html(_text(item.get("description")))
        for section in item.get("lists", []) or []:
            body += "\n\n" + _text(section.get("text")) + "\n" + strip_html(_text(section.get("content")))
        if item.get("additionalPlain"):
            body += "\n\n" + _text(item.get("additionalPlain"))
        commitment = _text(categories.get("commitment")).lower()
        jobs.append(_job(
            company,
            title=_text(item.get("text")),
            url=_text(item.get("hostedUrl") or item.get("applyUrl")),
            location=_text(categories.get("location")),
            description=body.strip(),
            source="lever",
            posted_at=_iso_from_millis(item.get("createdAt")),
            employment_type="internship" if "intern" in commitment
            else "contract" if "contract" in commitment else "full_time",
        ))
    return jobs


def _iso_from_millis(value: Any) -> str:
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


# --------------------------------------------------------------------------
# Ashby
# --------------------------------------------------------------------------

def ashby(client: Client, company: Company, slug: str) -> list[Job]:
    url = (f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
           "?includeCompensation=true")
    data = client.get_json(url)
    jobs = []
    for item in data.get("jobs", []) or []:
        comp = item.get("compensation") or {}
        summary = _text(comp.get("compensationTierSummary"))
        jobs.append(_job(
            company,
            title=_text(item.get("title")),
            url=_text(item.get("jobUrl") or item.get("applyUrl")),
            location=_text(item.get("location")),
            description=_text(item.get("descriptionPlain")) or strip_html(_text(item.get("descriptionHtml"))),
            source="ashby",
            posted_at=_text(item.get("publishedAt")),
            remote=bool(item.get("isRemote")),
            employment_type=_ashby_type(_text(item.get("employmentType"))),
            salary_text=summary,
        ))
    return jobs


def _ashby_type(value: str) -> str:
    v = value.lower()
    if "intern" in v:
        return "internship"
    if "contract" in v or "temporary" in v:
        return "contract"
    return "full_time"


# --------------------------------------------------------------------------
# Workable
# --------------------------------------------------------------------------

def workable(client: Client, company: Company, slug: str) -> list[Job]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    data = client.get_json(url)
    jobs = []
    for item in data.get("jobs", []) or []:
        location = ", ".join(
            part for part in (_text(item.get("city")), _text(item.get("country"))) if part)
        description = strip_html(_text(item.get("description")) + "\n" + _text(item.get("requirements")))
        jobs.append(_job(
            company,
            title=_text(item.get("title")),
            url=_text(item.get("url") or item.get("application_url")),
            location=location or _text(item.get("location")),
            description=description,
            source="workable",
            posted_at=_text(item.get("published_on") or item.get("created_at")),
            remote=bool(item.get("telecommuting")),
        ))
    return jobs


# --------------------------------------------------------------------------
# Recruitee
# --------------------------------------------------------------------------

def recruitee(client: Client, company: Company, slug: str) -> list[Job]:
    url = f"https://{slug}.recruitee.com/api/offers/"
    data = client.get_json(url)
    jobs = []
    for item in data.get("offers", []) or []:
        location = ", ".join(p for p in (_text(item.get("city")), _text(item.get("country_code"))) if p)
        jobs.append(_job(
            company,
            title=_text(item.get("title")),
            url=_text(item.get("careers_url") or item.get("careers_apply_url")),
            location=location,
            description=strip_html(_text(item.get("description")) + "\n" + _text(item.get("requirements"))),
            source="recruitee",
            posted_at=_text(item.get("published_at")),
            remote=_text(item.get("remote")).lower() == "true",
        ))
    return jobs


ATS_CONNECTORS: dict[str, Callable[[Client, Company, str], list[Job]]] = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "recruitee": recruitee,
}


def fetch_company_jobs(client: Client, company: Company) -> tuple[list[Job], str]:
    """Fetch a company's open roles. Returns (jobs, note)."""
    provider = (company.ats or {}).get("provider", "").lower()
    slug = (company.ats or {}).get("slug", "")
    if not provider or not slug:
        return [], "no ATS configured - run `jobpilot probe` or add ats.provider/ats.slug"
    fn = ATS_CONNECTORS.get(provider)
    if fn is None:
        return [], f"unsupported ATS provider '{provider}'"
    try:
        return fn(client, company, slug), ""
    except FetchError as exc:
        return [], str(exc)


def probe_ats(client: Client, company: Company, candidate_slugs: Iterable[str] | None = None
              ) -> tuple[str, str] | None:
    """Try to discover which ATS a company uses. Returns (provider, slug)."""
    slugs = list(candidate_slugs or [])
    if not slugs:
        base = company.key.replace("_", "")
        slugs = [base, company.key.replace("_", "-"),
                 company.name.lower().replace(" ", "").replace(".", "")]
    seen: set[str] = set()
    for slug in slugs:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        for provider, fn in ATS_CONNECTORS.items():
            try:
                jobs = fn(client, company, slug)
            except FetchError:
                continue
            if jobs:
                return provider, slug
    return None
