"""Flatten packages into the one wide table everything else renders."""

from __future__ import annotations

from typing import Any

from ..pipeline import Package

COLUMNS: list[tuple[str, str]] = [
    ("priority", "Priority"),
    ("company", "Company"),
    ("role", "Role"),
    ("overall", "Overall %"),
    ("technical", "Technical %"),
    ("eligibility", "Eligibility %"),
    ("domain", "Domain fit %"),
    ("salary", "Salary"),
    ("location", "Location"),
    ("mode", "Route"),
    ("contact_name", "Contact"),
    ("contact_title", "Contact title"),
    ("contact_email", "Contact email"),
    ("contact_email_status", "Email status"),
    ("contact_link", "Contact link"),
    ("resume", "Tailored CV"),
    ("email_subject", "Email subject"),
    ("email_body", "Email to send"),
    ("linkedin_note", "LinkedIn note"),
    ("why", "Why you match"),
    ("gaps", "Gaps"),
    ("verdict", "Verdict"),
    ("job_url", "Job link"),
    ("status", "Status"),
    ("new", "New"),
    ("first_seen", "First seen"),
    ("source", "Source"),
    ("searches", "Searches to find a human"),
]


def _salary(package: Package) -> str:
    job = package.job
    if job.salary_text:
        return job.salary_text
    if job.salary_min_lpa:
        top = f"-{job.salary_max_lpa:g}" if job.salary_max_lpa else "+"
        return f"₹{job.salary_min_lpa:g}{top} LPA"
    return ""


def package_rows(packages: list[Package]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for package in packages:
        assessment, job, draft = package.assessment, package.job, package.draft
        person = package.person
        searches = package.plan.get("searches", []) if package.plan else []
        inboxes = package.plan.get("generic_inboxes", []) if package.plan else []
        fallback_email = inboxes[0].email if inboxes and not person else ""
        rows.append({
            "priority": assessment.band.value,
            "company": job.company_name,
            "role": job.title,
            "overall": assessment.overall,
            "technical": assessment.technical_match,
            "eligibility": assessment.eligibility,
            "domain": assessment.domain_fit,
            "salary": _salary(package),
            "location": job.location + (" (remote)" if job.remote else ""),
            "mode": assessment.mode.value,
            "contact_name": person.name if person else "",
            "contact_title": person.title if person else "",
            "contact_email": (person.email if person else "") or fallback_email,
            "contact_email_status": (person.email_status if person else
                                     ("pattern_guess - verify" if fallback_email else "not found")),
            "contact_link": person.linkedin if person else "",
            "resume": package.resume_html_path,
            "email_subject": draft.subject if draft else "",
            "email_body": draft.body if draft else "",
            "linkedin_note": draft.linkedin_note if draft else "",
            "why": "; ".join(assessment.strengths[:5]),
            "gaps": "; ".join(assessment.gaps[:4]) or "-",
            "verdict": assessment.verdict,
            "job_url": job.url,
            "status": package.status.value,
            "new": "yes" if package.is_new else "",
            "first_seen": package.first_seen[:10],
            "source": job.source,
            "searches": "\n".join(str(s) for s in searches[:4]),
        })
    return rows
