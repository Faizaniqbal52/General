"""Load job postings from local files.

Two uses: the bundled demo corpus, and the realistic day-to-day case where you
paste a JD you found somewhere the agent cannot fetch (a LinkedIn post, a
WhatsApp forward, a PDF). Drop it in a directory as .json / .md / .txt and it
flows through the same parser, matcher, resume and outreach stages.

Markdown/text files use a light front-matter block:

    company: Sarvam AI
    title: NLP Engineer
    location: Bengaluru
    url: https://...
    salary: 18-32 LPA
    ---
    <the job description text>
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..models import Job
from ..textutil import slugify, strip_html

_FRONT_KEYS = {"company", "company_key", "title", "location", "url", "salary",
               "posted", "posted_at", "remote", "type", "employment_type", "source"}


def _from_mapping(raw: dict[str, Any], fallback_source: str) -> Job:
    company_name = str(raw.get("company") or raw.get("company_name") or "Unknown")
    company_key = str(raw.get("company_key") or slugify(company_name)).replace("-", "_")
    title = str(raw.get("title") or "Unspecified role")
    url = str(raw.get("url") or "")
    location = str(raw.get("location") or "")
    description = str(raw.get("description") or raw.get("body") or "")
    if "<" in description and ">" in description:
        description = strip_html(description)
    remote_raw = raw.get("remote")
    remote = str(remote_raw).strip().lower() in {"1", "true", "yes", "remote"} if remote_raw is not None else False
    return Job(
        id=str(raw.get("id") or Job.make_id(company_key, title, url, location)),
        company_key=company_key,
        company_name=company_name,
        title=title,
        url=url,
        location=location,
        remote=remote,
        description=description,
        employment_type=str(raw.get("employment_type") or raw.get("type") or "full_time"),
        salary_text=str(raw.get("salary") or raw.get("salary_text") or ""),
        posted_at=str(raw.get("posted_at") or raw.get("posted") or "")[:10],
        source=str(raw.get("source") or fallback_source),
    )


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in {"---", "==="}:
            body_start = i + 1
            break
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip().lower()
            if key in _FRONT_KEYS:
                meta[key] = value.strip()
                continue
        if stripped == "" and meta:
            body_start = i + 1
            break
        if not meta:
            body_start = i
            break
    return meta, "\n".join(lines[body_start:]).strip()


def load_local_jobs(path: str | Path, source: str = "local") -> list[Job]:
    path = Path(path)
    if not path.exists():
        return []
    files: Iterable[Path]
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.suffix.lower() in {".json", ".md", ".txt"})
    else:
        files = [path]

    jobs: list[Job] = []
    for file in files:
        text = file.read_text(encoding="utf-8")
        if file.suffix.lower() == ".json":
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("jobs", [data])
            jobs.extend(_from_mapping(item, source) for item in items if isinstance(item, dict))
        else:
            meta, body = _parse_front_matter(text)
            meta["description"] = body
            meta.setdefault("title", file.stem.replace("_", " ").title())
            jobs.append(_from_mapping(meta, source))
    return jobs
