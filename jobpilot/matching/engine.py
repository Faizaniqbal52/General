"""Scoring: eligibility, technical match, domain fit, priority and verdict.

Two numbers, not one. "Can I realistically apply?" (eligibility) and "can I
actually do the work?" (technical match) fail for completely different reasons,
and collapsing them into a single percentage hides the only thing you need to
know: whether the gap is fixable by writing a better email or not fixable at all.
"""

from __future__ import annotations

from ..models import (
    Assessment, Band, Company, Job, Level, Mode, Necessity, Profile,
    Requirement, RequirementMatch,
)
from ..parsing.jd import job_domains
from ..parsing.taxonomy import label_of

# Partial credit between neighbouring skills. "I know PyTorch, not TensorFlow"
# is a much smaller gap than "I have never trained a model".
ADJACENT: dict[str, dict[str, float]] = {
    "tensorflow": {"pytorch": 0.55, "jax": 0.4, "deep_learning": 0.35},
    "pytorch": {"tensorflow": 0.45, "jax": 0.4, "deep_learning": 0.4},
    "jax": {"pytorch": 0.5, "tensorflow": 0.4},
    "gcp": {"aws": 0.6, "azure": 0.5, "docker": 0.2},
    "aws": {"gcp": 0.6, "azure": 0.5, "docker": 0.2},
    "azure": {"aws": 0.6, "gcp": 0.6},
    "kubernetes": {"docker": 0.45, "mlops": 0.3, "linux": 0.2},
    "mlops": {"docker": 0.35, "backend": 0.3, "distributed_training": 0.3},
    "distributed_training": {"pytorch": 0.35, "mlops": 0.3},
    "rag": {"llm": 0.5, "nlp": 0.3, "search": 0.3},
    "agents": {"llm": 0.5, "backend": 0.25, "rag": 0.4},
    "llm_finetuning": {"llm": 0.5, "pytorch": 0.4, "huggingface": 0.45},
    "llm": {"nlp": 0.5, "llm_finetuning": 0.6, "huggingface": 0.4},
    "nlp": {"llm": 0.5, "low_resource_nlp": 0.6, "deep_learning": 0.3},
    "low_resource_nlp": {"nlp": 0.6, "llm": 0.35},
    "cv": {"ocr": 0.6, "deep_learning": 0.35, "multimodal": 0.4},
    "ocr": {"cv": 0.6, "document_ai": 0.5, "deep_learning": 0.3},
    "multimodal": {"cv": 0.45, "nlp": 0.4, "llm": 0.4},
    "speech": {"nlp": 0.3, "deep_learning": 0.3, "multimodal": 0.35},
    "sklearn": {"python": 0.4, "ml": 0.5, "numpy": 0.35},
    "ml": {"deep_learning": 0.6, "sklearn": 0.5},
    "deep_learning": {"pytorch": 0.6, "ml": 0.5},
    "backend": {"python": 0.35, "system_design": 0.35},
    "frontend": {"javascript": 0.5},
    "typescript": {"javascript": 0.7},
    "javascript": {"typescript": 0.7},
    "cicd": {"git": 0.35, "docker": 0.3},
    "system_design": {"backend": 0.4, "mlops": 0.25},
    "cpp": {"c": 0.6, "rust": 0.3},
    "c": {"cpp": 0.6},
    "recsys": {"ml": 0.4, "search": 0.4},
    "onnx": {"pytorch": 0.35, "mlops": 0.35},
    "huggingface": {"pytorch": 0.4, "llm": 0.4},
    "evaluation": {"research": 0.4, "ml": 0.3},
}

WEIGHTS = {"technical": 0.45, "domain": 0.25, "eligibility": 0.30}

# With no posting there is no requirement list to match against, so the honest
# signal is "does this company work on what I have evidence in", not keywords.
# The result is also discounted: a confirmed opening beats a speculative letter,
# and A+ is reserved for real postings.
WEIGHTS_SPECULATIVE = {"technical": 0.20, "domain": 0.55, "eligibility": 0.25}
SPECULATIVE_DISCOUNT = 0.88

BANDS = ((85.0, Band.A_PLUS), (72.0, Band.A), (58.0, Band.B), (45.0, Band.C))

# skills a fresh graduate is not expected to have; softens their gap penalty
_SENIOR_ONLY = {"kubernetes", "system_design", "cicd", "distributed_training", "mlops"}


def _requirement_score(profile: Profile, req: Requirement) -> tuple[float, Level, list[str]]:
    """0..1 coverage of one requirement, with the evidence that supports it."""
    skill = profile.skill(req.skill)
    direct = skill.credibility if skill else 0.0

    # adjacent skills give partial, clearly-labelled credit, capped below a
    # genuine claim: knowing PyTorch is real evidence for a TensorFlow role,
    # but it is not the same as having used TensorFlow.
    near_best, near_ids = 0.0, []
    for neighbour, factor in ADJACENT.get(req.skill, {}).items():
        near = profile.skill(neighbour)
        if near and near.credibility > 0:
            value = min(near.credibility * factor, 0.6)
            if value > near_best:
                near_best, near_ids = value, list(near.evidence)

    if direct >= near_best and direct > 0:
        return direct, skill.level, list(skill.evidence)
    if near_best > 0:
        return near_best, (skill.level if skill else Level.NONE), near_ids

    if req.skill in {w.lower() for w in profile.constraints.willing_to_learn}:
        return 0.15, Level.NONE, []
    return 0.0, Level.NONE, []


def score_requirements(profile: Profile, job: Job) -> list[RequirementMatch]:
    out: list[RequirementMatch] = []
    for req in job.requirements:
        score, level, ids = _requirement_score(profile, req)
        out.append(RequirementMatch(requirement=req, your_level=level, score=score, evidence_ids=ids))
    return out


def technical_match(matches: list[RequirementMatch]) -> float:
    if not matches:
        return 50.0                      # nothing parsed - stay neutral, don't reward or punish
    total = sum(m.requirement.weight for m in matches)
    got = sum(m.requirement.weight * m.score for m in matches)
    return round(100.0 * got / total, 1) if total else 50.0


def domain_fit(profile: Profile, job: Job, company: Company | None) -> tuple[float, list[str]]:
    """How close the company's problem space is to what you have actually built."""
    about = company.about if company else ""
    hits = job_domains(job, about)
    if company:
        for d in company.domains:
            hits[d] = hits.get(d, 0) + 2

    if not hits:
        return 50.0, []

    mine = profile.domains()
    # weight your domains by how much evidence sits behind them
    strength: dict[str, float] = {}
    for ev in profile.evidence.values():
        for d in ev.domains:
            strength[d] = min(1.0, strength.get(d, 0.0) + 0.5)
    for d in profile.preferences.domains:
        strength.setdefault(d, 0.4)

    total = sum(hits.values())
    covered = sum(count * strength.get(d, 0.0) for d, count in hits.items())
    overlap = [label_of(d) for d in sorted(hits, key=hits.get, reverse=True)
               if d in mine and strength.get(d, 0) >= 0.4]
    raw = 100.0 * covered / total if total else 50.0
    # a partial overlap on a specialised domain is worth more than a broad miss
    if overlap:
        raw = max(raw, 60.0 + 8.0 * len(overlap))
    return round(min(raw, 100.0), 1), overlap[:5]


def eligibility(profile: Profile, job: Job) -> tuple[float, list[str], list[str]]:
    """Return (score, blockers, soft notes). Blockers force a SKIP."""
    score = 100.0
    blockers: list[str] = []
    notes: list[str] = []
    prefs, cons = profile.preferences, profile.constraints

    title = job.title.lower()
    for word in prefs.avoid:
        if word and word in title:
            blockers.append(f"title matches your avoid list ('{word}')")

    # experience
    if job.min_years is not None:
        gap = job.min_years - cons.years_experience
        if gap >= 4:
            blockers.append(
                f"asks for {job.min_years:g}+ years, you have {cons.years_experience:g}")
        elif gap > 0:
            score -= min(38.0, gap * 13.0)
            notes.append(
                f"{job.min_years:g}+ years requested vs {cons.years_experience:g} - "
                "the usual student gap, worth applying if the technical match is strong")
    if job.seniority in {"senior"} and cons.years_experience < 3:
        score -= 25.0
        notes.append("posting is pitched at senior/lead level")

    # degree
    order = {"": 0, "bachelors": 1, "masters": 2, "phd": 3}
    have, want = order.get(cons.highest_degree, 0), order.get(job.degree_required, 0)
    if want > have:
        if want == 3:
            blockers.append("PhD required")
        else:
            score -= 15.0
            notes.append(f"{job.degree_required} preferred, you hold {cons.highest_degree or 'n/a'}")

    # employment type
    if job.employment_type not in prefs.employment_types:
        blockers.append(f"{job.employment_type.replace('_', ' ')} is not in your accepted types")

    # location / remote
    if not job.remote:
        loc = (job.location or "").lower()
        wanted = [l.lower() for l in prefs.locations]
        if loc and wanted and not any(w in loc or loc in w for w in wanted):
            if prefs.relocate_ok:
                score -= 8.0
                notes.append(f"onsite in {job.location} - would need relocation")
            else:
                blockers.append(f"onsite in {job.location}, outside your locations")
        if not prefs.onsite_ok:
            blockers.append("role is onsite and you only want remote")
    elif not prefs.remote_ok:
        score -= 5.0

    # work authorisation - only trust an explicit country mention
    loc = (job.location or "").lower()
    authorised = [a.lower() for a in cons.work_authorization]
    if loc and "india" not in loc and not job.remote:
        if not any(a in loc for a in authorised) and "india" in authorised:
            known_in = any(city in loc for city in _INDIAN_CITIES)
            if not known_in:
                blockers.append(f"location '{job.location}' looks outside your work authorisation")

    # salary
    if prefs.min_salary_lpa and job.salary_max_lpa:
        if job.salary_max_lpa < prefs.min_salary_lpa:
            score -= 20.0
            notes.append(
                f"top of band {job.salary_max_lpa:g} LPA is under your {prefs.min_salary_lpa:g} LPA floor")

    return round(max(0.0, min(score, 100.0)), 1), blockers, notes


_INDIAN_CITIES = {
    "bengaluru", "bangalore", "hyderabad", "chennai", "mumbai", "pune", "delhi",
    "gurugram", "gurgaon", "noida", "kolkata", "ahmedabad", "jaipur", "kochi",
    "thiruvananthapuram", "indore", "chandigarh", "bhubaneswar", "srinagar",
    "coimbatore", "mysuru", "mysore", "hosur", "vizag", "visakhapatnam",
}


def choose_mode(job: Job, company: Company | None, has_posting: bool) -> Mode:
    if has_posting:
        return Mode.DIRECT
    if company and company.outreach_modes:
        try:
            return Mode(company.outreach_modes[0])
        except ValueError:
            pass
    if company and company.stage in {"pre_seed", "seed", "early", "series_a"} and company.founders:
        return Mode.FOUNDER
    if company and {"research", "foundation_models"} & set(company.domains):
        return Mode.TECHNICAL
    return Mode.RECRUITER


def band_for(overall: float, blockers: list[str]) -> Band:
    if blockers:
        return Band.SKIP
    for threshold, band in BANDS:
        if overall >= threshold:
            return band
    return Band.SKIP


def _verdict(band: Band, job: Job, company_name: str, strengths: list[str],
             gaps: list[str], blockers: list[str], mode: Mode,
             tech: float, elig: float) -> str:
    if band is Band.SKIP:
        reason = blockers[0] if blockers else "match is too thin to be worth your time"
        return (f"SKIP - {reason}.\n"
                f"Technical match {tech:g}/100, eligibility {elig:g}/100.\n"
                "Spend the hour on a company where your evidence actually lands.")
    head = {
        Band.A_PLUS: "APPLY - TOP PRIORITY",
        Band.A: "APPLY - HIGH PRIORITY",
        Band.B: "WORTH APPLYING",
        Band.C: "LOW PRIORITY - only if you have spare time",
    }[band]
    strength_line = (", ".join(strengths[:4]) if strengths
                     else "general overlap with your stack")
    gap_line = gaps[0] if gaps else "no material gap in the stated requirements"
    route = {
        Mode.DIRECT: "Apply through the posting, then follow up with a named person.",
        Mode.RECRUITER: "No exact posting - approach a recruiter or hiring manager directly.",
        Mode.FOUNDER: "Small team - write to the founder with the work, not a CV blast.",
        Mode.TECHNICAL: "Go to the ML/research lead with a technical note, not to HR.",
    }[mode]
    return (f"{head} - {job.title} at {company_name}.\n"
            f"Your strongest ground here: {strength_line}. Main gap: {gap_line}.\n"
            f"{route}")


def assess(profile: Profile, job: Job, company: Company | None = None,
           has_posting: bool = True) -> Assessment:
    matches = score_requirements(profile, job)
    tech = technical_match(matches)
    dom, overlap = domain_fit(profile, job, company)
    elig, blockers, notes = eligibility(profile, job)

    weights = WEIGHTS if has_posting else WEIGHTS_SPECULATIVE
    overall = (weights["technical"] * tech
               + weights["domain"] * dom
               + weights["eligibility"] * elig)
    if not has_posting:
        overall *= SPECULATIVE_DISCOUNT
    overall = round(overall, 1)
    band = band_for(overall, blockers)
    if band is Band.A_PLUS and not has_posting:
        band = Band.A
    mode = choose_mode(job, company, has_posting)

    strengths = [m.requirement.label for m in sorted(matches, key=lambda m: -m.score)
                 if m.score >= 0.7][:6]
    strengths += [d for d in overlap if d not in strengths][:2]

    gaps: list[str] = []
    for m in sorted(matches, key=lambda m: m.score):
        if m.is_gap:
            suffix = " (expected of a fresher)" if m.requirement.skill in _SENIOR_ONLY else ""
            gaps.append(f"{m.requirement.label}{suffix}")
    gaps += notes
    gaps = gaps[:6]

    evidence_ids: list[str] = []
    for m in sorted(matches, key=lambda m: -m.score):
        for eid in m.evidence_ids:
            if eid not in evidence_ids:
                evidence_ids.append(eid)

    return Assessment(
        job_id=job.id,
        eligibility=elig,
        technical_match=tech,
        domain_fit=dom,
        overall=overall,
        band=band,
        mode=mode,
        verdict=_verdict(band, job, company.name if company else job.company_name,
                         strengths, gaps, blockers, mode, tech, elig),
        strengths=strengths,
        gaps=gaps,
        blockers=blockers,
        matches=matches,
        evidence_ids=evidence_ids,
    )
