"""The orchestrator: profile -> discovery -> matching -> package -> database.

`run()` is one pass of the whole agent. It is safe to run repeatedly: postings
already in the database are recognised, so each run can tell you what is new,
and your application statuses are never overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import fetch_company_jobs, load_local_jobs, load_registry
from .llm import Enricher, from_env as llm_from_env
from .matching.engine import assess
from .models import (Application, Assessment, Band, Company, Job, Mode, Person, Profile,
                     Status)
from .net import Client
from .outreach import build_drafts, contact_plan, load_people
from .outreach.messages import OutreachDraft
from .parsing.jd import enrich
from .parsing.taxonomy import looks_like_target_role
from .profile import load_profile
from .resume import build_resume, render_html, render_markdown, verify_resume
from .store import Store
from .textutil import slugify

BAND_ORDER = [Band.A_PLUS, Band.A, Band.B, Band.C, Band.SKIP]

_INDIA_HINTS = {"india", "bengaluru", "bangalore", "hyderabad", "chennai", "mumbai", "pune",
                "delhi", "gurugram", "gurgaon", "noida", "kolkata", "ahmedabad", "jaipur",
                "kochi", "trivandrum", "thiruvananthapuram", "indore", "chandigarh", "srinagar",
                "bhubaneswar", "coimbatore", "mysuru", "mysore", "hosur", "visakhapatnam",
                "remote"}


@dataclass
class Config:
    profile_path: str = "profile.yaml"
    db_path: str = "jobpilot.db"
    out_dir: str = "out"
    company_files: list[str] = field(default_factory=list)
    people_file: str = "people.yaml"
    local_jobs: list[str] = field(default_factory=list)
    cache_dir: str = ".jobpilot-cache"
    offline: bool = False
    india_only: bool = True
    role_filter: bool = True
    include_open_applications: bool = True
    min_band: Band = Band.C
    max_jobs_per_company: int = 60
    company_keys: list[str] = field(default_factory=list)
    company_domains: list[str] = field(default_factory=list)
    use_llm: bool = False


@dataclass
class Package:
    """Everything the dashboard shows for one opportunity."""
    job: Job
    company: Company | None
    assessment: Assessment
    resume_md_path: str = ""
    resume_html_path: str = ""
    person: Person | None = None
    draft: OutreachDraft | None = None
    plan: dict[str, object] = field(default_factory=dict)
    is_new: bool = False
    status: Status = Status.NOT_CONTACTED
    first_seen: str = ""


@dataclass
class RunReport:
    packages: list[Package] = field(default_factory=list)
    fetched: int = 0
    filtered_out: int = 0
    new_jobs: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def by_band(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for package in self.packages:
            out[package.assessment.band.value] = out.get(package.assessment.band.value, 0) + 1
        return out


def _in_india(job: Job) -> bool:
    blob = f"{job.location} {job.company_name}".lower()
    if job.remote:
        return True
    if not job.location:
        return True                       # unknown location - let the matcher judge it
    return any(hint in blob for hint in _INDIA_HINTS)


def _open_application_job(company: Company) -> Job:
    """A synthetic 'there is no posting, but this company is worth a letter' entry."""
    from .parsing.taxonomy import label_of
    focus = " / ".join(label_of(d) for d in company.domains[:2]) or "AI/ML"
    title = f"Open application - {focus}"
    description = (f"{company.about}\n\n"
                   f"Focus areas: {focus}. Stage: {company.stage or 'unknown'}.")
    job = Job(
        id=Job.make_id(company.key, title, company.website or company.key, company.hq),
        company_key=company.key,
        company_name=company.name,
        title=title,
        url=company.careers_url or company.website,
        location=company.hq,
        description=description,
        source="open_application",
    )
    return enrich(job)


def collect_jobs(config: Config, registry, client: Client | None) -> tuple[list[Job], dict[str, Company], list[str]]:
    companies = {c.key: c for c in registry.select(
        keys=config.company_keys or None, domains=config.company_domains or None)}
    errors: list[str] = []
    jobs: list[Job] = []

    if client is not None:
        for company in companies.values():
            if not company.ats.get("slug"):
                continue
            found, note = fetch_company_jobs(client, company)
            if note:
                errors.append(f"{company.name}: {note}")
            jobs.extend(found[: config.max_jobs_per_company])

    for path in config.local_jobs:
        local = load_local_jobs(path)
        for job in local:
            companies.setdefault(job.company_key, Company(key=job.company_key,
                                                          name=job.company_name,
                                                          source="local"))
        jobs.extend(local)

    if config.include_open_applications:
        with_postings = {job.company_key for job in jobs}
        for company in companies.values():
            if company.key in with_postings or not company.outreach_modes:
                continue
            jobs.append(_open_application_job(company))

    return jobs, companies, errors


def _keep(job: Job, config: Config) -> bool:
    if job.source == "open_application":
        return True
    if config.role_filter and not looks_like_target_role(job.title):
        return False
    if config.india_only and not _in_india(job):
        return False
    return True


def _resume_paths(out_dir: Path, profile: Profile, job: Job) -> tuple[Path, Path]:
    folder = out_dir / "resumes"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{slugify(profile.name.split()[0])}_{slugify(job.company_name)}_{slugify(job.title)}"
    stem = re.sub(r"-+", "-", stem)[:90]
    return folder / f"{stem}.md", folder / f"{stem}.html"


def run(config: Config) -> RunReport:
    profile = load_profile(config.profile_path)
    registry = load_registry(config.company_files)
    people = load_people(config.people_file)
    enricher: Enricher = llm_from_env(config.use_llm)
    report = RunReport()
    if config.use_llm and not enricher.available:
        report.notes.append("--llm requested but no API key/SDK available; using rules only")

    client = None
    if not config.offline:
        client = Client(cache_dir=config.cache_dir)

    jobs, companies, errors = collect_jobs(config, registry, client)
    report.errors.extend(errors)
    report.fetched = len(jobs)

    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    min_index = BAND_ORDER.index(config.min_band)

    with Store(config.db_path) as store:
        for person in people.values():
            store.upsert_person(person)
        for company in companies.values():
            store.upsert_company(company)

        seen: set[str] = set()
        for job in jobs:
            if job.id in seen:
                continue
            seen.add(job.id)
            if not _keep(job, config):
                report.filtered_out += 1
                continue
            if job.source != "open_application":
                enrich(job)
            if enricher.available:
                job.requirements = enricher.extend_requirements(job)
            company = companies.get(job.company_key)
            assessment = assess(profile, job, company,
                                has_posting=job.source != "open_application")

            is_new = store.upsert_job(job)
            store.upsert_assessment(assessment)
            report.new_jobs += int(is_new)

            if BAND_ORDER.index(assessment.band) > min_index:
                continue

            resume = build_resume(profile, job, assessment)
            verify_resume(resume, profile)
            md_path, html_path = _resume_paths(out_dir, profile, job)
            md_path.write_text(render_markdown(resume, include_notes=True), encoding="utf-8")
            html_path.write_text(render_html(resume), encoding="utf-8")

            company_for_contact = company or Company(key=job.company_key, name=job.company_name)
            plan = contact_plan(company_for_contact, job, assessment.mode, people)
            person = plan.get("best_contact")  # type: ignore[assignment]
            draft = build_drafts(profile, job, assessment, company, person)
            if enricher.available:
                draft.body = enricher.polish_email(draft.body)

            application = Application(
                job_id=job.id,
                resume_path=str(html_path),
                person_key=person.key if person else "",
                email_subject=draft.subject,
                email_body=draft.body,
                linkedin_message=draft.linkedin_message,
                followup_body=draft.followup_body,
            )
            store.upsert_application(application)
            stored = store.get_application(job.id)

            report.packages.append(Package(
                job=job, company=company, assessment=assessment,
                resume_md_path=str(md_path), resume_html_path=str(html_path),
                person=person, draft=draft, plan=plan, is_new=is_new,
                status=stored.status if stored else Status.NOT_CONTACTED,
                first_seen=store.first_seen(job.id),
            ))
        store.commit()

    report.packages.sort(key=lambda p: (BAND_ORDER.index(p.assessment.band), -p.assessment.overall))
    return report
