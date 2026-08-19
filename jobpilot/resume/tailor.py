"""Tailor one fixed resume template to a specific job.

The template never changes. What changes is which evidence is selected, which
highlights inside that evidence are shown, and in what order the skills appear.

The hard rule: `build_resume` can only ever emit strings that already exist in
the profile (plus the fixed section labels). `verify_resume` re-checks that
after the fact and raises if anything slipped through, so a tailored resume can
never contain a skill you do not have or a claim you cannot defend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Assessment, Evidence, Job, Level, Profile
from ..parsing.taxonomy import category_of, extract_skills, label_of
from ..textutil import first_sentence

CATEGORY_ORDER = ["language", "ml", "ml_framework", "software", "research", "soft", "other"]
CATEGORY_LABELS = {
    "language": "Languages",
    "ml": "Machine learning",
    "ml_framework": "ML tooling",
    "software": "Engineering",
    "research": "Research",
    "soft": "Other",
    "other": "Other",
}


@dataclass
class ResumeItem:
    evidence_id: str
    name: str
    role: str
    period: str
    summary: str
    highlights: list[str]
    links: list[str]
    relevance: float
    why: str


@dataclass
class TailoredResume:
    job_id: str
    company_name: str
    job_title: str
    name: str
    contact: dict[str, str]
    headline: str
    summary: str
    skill_groups: list[tuple[str, list[str]]]
    projects: list[ResumeItem]
    experience: list[ResumeItem]
    publications: list[ResumeItem]
    education: list[dict[str, str]]
    achievements: list[str] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]{3,}", (text or "").lower())}


def _job_signal(job: Job) -> tuple[set[str], set[str]]:
    """(required skill keys, all skill keys) that the job cares about."""
    required = {r.skill for r in job.requirements if r.necessity.value == "required"}
    every = {r.skill for r in job.requirements}
    every |= set(extract_skills(job.title))
    return required, every


def _relevance(ev: Evidence, required: set[str], every: set[str],
               job_tokens: set[str], job_domains: set[str]) -> float:
    skills = set(ev.skills)
    score = 3.0 * len(skills & required) + 1.2 * len(skills & (every - required))
    score += 2.0 * len(set(ev.domains) & job_domains)
    overlap = _tokens(ev.text()) & job_tokens
    score += 0.15 * min(len(overlap), 12)
    return round(score, 2)


def _rank_highlights(ev: Evidence, required: set[str], job_tokens: set[str],
                     limit: int) -> list[str]:
    if not ev.highlights:
        return []
    scored = []
    for line in ev.highlights:
        line_skills = set(extract_skills(line))
        score = 2.0 * len(line_skills & required) + 0.2 * len(_tokens(line) & job_tokens)
        scored.append((score, line))
    ordered = [line for _, line in sorted(scored, key=lambda pair: -pair[0])]
    kept = ordered[:limit]
    # keep the author's original ordering among the ones we kept
    return [line for line in ev.highlights if line in kept]


def _why(ev: Evidence, required: set[str], job_domains: set[str]) -> str:
    hit_skills = [label_of(s) for s in ev.skills if s in required]
    hit_domains = [label_of(d) for d in ev.domains if d in job_domains]
    bits = []
    if hit_skills:
        bits.append("covers " + ", ".join(hit_skills[:4]))
    if hit_domains:
        bits.append("same problem space: " + ", ".join(hit_domains[:3]))
    return "; ".join(bits) or "general overlap with the role"


def _skill_groups(profile: Profile, required: set[str], every: set[str],
                  include_unevidenced: bool, per_group: int
                  ) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Grouped, JD-ordered skill lines plus the list of skills held back."""
    groups: dict[str, list[tuple[float, str]]] = {}
    excluded: list[str] = []
    for key, skill in profile.skills.items():
        if skill.level in {Level.NONE, Level.EXPLORATORY}:
            excluded.append(f"{skill.label} (level {skill.level.value})")
            continue
        if not skill.is_evidenced and not include_unevidenced:
            excluded.append(f"{skill.label} (no evidence in profile)")
            continue
        rank = skill.credibility
        if key in required:
            rank += 3.0
        elif key in every:
            rank += 1.5
        groups.setdefault(category_of(key), []).append((rank, skill.label))

    out: list[tuple[str, list[str]]] = []
    for category in CATEGORY_ORDER:
        items = groups.get(category)
        if not items:
            continue
        ordered = sorted(items, key=lambda pair: (-pair[0], pair[1].lower()))
        labels = [label for _, label in ordered[:per_group]]
        excluded.extend(f"{label} (trimmed - not relevant enough to this role)"
                        for _, label in ordered[per_group:])
        out.append((CATEGORY_LABELS.get(category, category.title()), labels))
    return out, sorted(excluded)


def _pick_achievements(profile: Profile, job_tokens: set[str], limit: int) -> list[str]:
    """Recognition lines, the most relevant few, in the order you wrote them."""
    if not profile.achievements:
        return []
    scored = [(len(_tokens(line) & job_tokens), line) for line in profile.achievements]
    kept = {line for _, line in sorted(scored, key=lambda pair: -pair[0])[:limit]}
    return [line for line in profile.achievements if line in kept]


def _summary(profile: Profile, job: Job, assessment: Assessment | None,
             top: list[ResumeItem]) -> str:
    """A summary line assembled only from profile text and the job's own title."""
    base = first_sentence(profile.narrative, 260) or profile.headline
    if not base:
        return ""
    anchors = []
    for item in top[:2]:
        anchors.append(item.name)
    if anchors:
        return f"{base} Most relevant work for this role: {', '.join(anchors)}."
    return base


def build_resume(profile: Profile, job: Job, assessment: Assessment | None = None,
                 *, max_projects: int = 4, max_highlights: int = 4,
                 max_achievements: int = 4, max_skills_per_group: int = 8,
                 include_unevidenced_skills: bool = False) -> TailoredResume:
    required, every = _job_signal(job)
    job_tokens = _tokens(f"{job.title} {job.description}")
    job_domains = set()
    if assessment:
        job_domains = {d.lower().replace(" ", "_").replace("/", "_") for d in assessment.strengths}
    from ..parsing.jd import job_domains as extract_job_domains
    job_domains |= set(extract_job_domains(job))

    def items_of(kind: str, limit: int) -> list[ResumeItem]:
        pool = [ev for ev in profile.evidence.values() if ev.kind == kind]
        scored = sorted(pool, key=lambda ev: -_relevance(ev, required, every, job_tokens, job_domains))
        out = []
        for ev in scored[:limit]:
            relevance = _relevance(ev, required, every, job_tokens, job_domains)
            out.append(ResumeItem(
                evidence_id=ev.id,
                name=ev.name,
                role=ev.role,
                period=ev.period,
                summary=first_sentence(ev.summary, 240),
                highlights=_rank_highlights(ev, required, job_tokens, max_highlights) or
                           ([first_sentence(ev.summary, 200)] if ev.summary else []),
                links=list(ev.links),
                relevance=relevance,
                why=_why(ev, required, job_domains),
            ))
        return out

    projects = items_of("project", max_projects)
    experience = items_of("experience", 3)
    publications = items_of("publication", 3)
    repos = items_of("repo", 1)
    if repos and len(projects) < max_projects:
        projects += repos

    groups, excluded = _skill_groups(profile, required, every, include_unevidenced_skills,
                                     max_skills_per_group)

    headline = profile.headline or job.title
    contact = {"email": profile.email, "phone": profile.phone, "location": profile.location}
    contact.update({k: v for k, v in profile.links.items() if v})

    footnotes = []
    if assessment and assessment.gaps:
        footnotes.append("Known gaps for this role (not on the resume, for your own notes): "
                         + "; ".join(assessment.gaps[:3]))

    return TailoredResume(
        job_id=job.id,
        company_name=job.company_name,
        job_title=job.title,
        name=profile.name,
        contact={k: v for k, v in contact.items() if v},
        headline=headline,
        summary=_summary(profile, job, assessment, projects + experience),
        skill_groups=groups,
        projects=projects,
        experience=experience,
        publications=publications,
        education=[{str(k): str(v) for k, v in row.items()} for row in profile.education],
        achievements=_pick_achievements(profile, job_tokens, max_achievements),
        footnotes=footnotes,
        excluded=excluded,
    )


class ResumeIntegrityError(AssertionError):
    """Raised when a tailored resume contains something the profile cannot back."""


def verify_resume(resume: TailoredResume, profile: Profile) -> None:
    """Fail loudly if anything on the resume is not traceable to the profile."""
    known_skill_labels = {s.label for s in profile.skills.values()}
    for _, labels in resume.skill_groups:
        for label in labels:
            if label not in known_skill_labels:
                raise ResumeIntegrityError(f"skill '{label}' is not in the profile")
            skill = next(s for s in profile.skills.values() if s.label == label)
            if skill.level in {Level.NONE, Level.EXPLORATORY}:
                raise ResumeIntegrityError(
                    f"skill '{label}' is only {skill.level.value} and must not be featured")

    for item in resume.projects + resume.experience + resume.publications:
        ev = profile.evidence.get(item.evidence_id)
        if ev is None:
            raise ResumeIntegrityError(f"'{item.name}' has no evidence entry in the profile")
        if item.name != ev.name:
            raise ResumeIntegrityError(f"renamed evidence '{ev.id}'")
        for line in item.highlights:
            if line not in ev.highlights and line not in first_sentence(ev.summary, 200):
                raise ResumeIntegrityError(
                    f"highlight on '{ev.id}' does not appear in the profile: {line[:60]}")
    for line in resume.achievements:
        if line not in profile.achievements:
            raise ResumeIntegrityError(f"achievement is not in the profile: {line[:60]}")

    if resume.summary and profile.narrative:
        stem = first_sentence(profile.narrative, 260) or profile.headline
        if stem and not resume.summary.startswith(stem):
            raise ResumeIntegrityError("summary was rewritten instead of assembled")
