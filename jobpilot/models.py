"""Core data structures shared by every stage of the pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Any


class Level(str, Enum):
    """How well you actually know a skill, and how much evidence backs it."""

    STRONG = "strong"
    INTERMEDIATE = "intermediate"
    BASIC = "basic"
    EXPLORATORY = "exploratory"
    NONE = "none"

    @property
    def weight(self) -> float:
        return {
            Level.STRONG: 1.0,
            Level.INTERMEDIATE: 0.7,
            Level.BASIC: 0.4,
            Level.EXPLORATORY: 0.2,
            Level.NONE: 0.0,
        }[self]

    @classmethod
    def parse(cls, value: Any) -> "Level":
        if isinstance(value, Level):
            return value
        text = str(value or "none").strip().lower()
        aliases = {
            "expert": cls.STRONG,
            "advanced": cls.STRONG,
            "high": cls.STRONG,
            "medium": cls.INTERMEDIATE,
            "moderate": cls.INTERMEDIATE,
            "working": cls.INTERMEDIATE,
            "beginner": cls.BASIC,
            "low": cls.BASIC,
            "familiar": cls.BASIC,
            "experimented": cls.EXPLORATORY,
            "learning": cls.EXPLORATORY,
        }
        if text in aliases:
            return aliases[text]
        try:
            return cls(text)
        except ValueError:
            return cls.NONE


class Necessity(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"

    @property
    def weight(self) -> float:
        return 1.0 if self is Necessity.REQUIRED else 0.35


class Mode(str, Enum):
    """How to approach an opportunity."""

    DIRECT = "direct"          # A - there is a posting, apply to it
    RECRUITER = "recruiter"    # B - relevant team, no perfect posting
    FOUNDER = "founder"        # C - early stage, write to the founder
    TECHNICAL = "technical"    # D - go to the ML/research lead, not HR


class Band(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    SKIP = "SKIP"


class Status(str, Enum):
    NOT_CONTACTED = "not_contacted"
    EMAIL_SENT = "email_sent"
    LINKEDIN_CONTACTED = "linkedin_contacted"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    FOLLOW_UP = "follow_up"


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


@dataclass
class Evidence:
    """A project, role, paper or repository that proves you can do something."""

    id: str
    kind: str                       # project | experience | publication | repo | cert
    name: str
    summary: str = ""
    role: str = ""
    period: str = ""
    highlights: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts = [self.name, self.summary, self.role, *self.highlights, *self.metrics]
        parts += self.skills + self.domains
        return " ".join(p for p in parts if p)


@dataclass
class Skill:
    name: str                       # canonical skill key
    label: str                      # how it should be printed
    level: Level = Level.NONE
    evidence: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def is_evidenced(self) -> bool:
        return bool(self.evidence)

    @property
    def credibility(self) -> float:
        """Level weight, discounted when nothing in the profile backs it up."""
        return self.level.weight if self.is_evidenced else self.level.weight * 0.5


@dataclass
class Preferences:
    roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_ok: bool = True
    onsite_ok: bool = True
    relocate_ok: bool = False
    employment_types: list[str] = field(default_factory=lambda: ["full_time", "internship"])
    min_salary_lpa: float | None = None
    domains: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)


@dataclass
class Constraints:
    graduation_year: int | None = None
    years_experience: float = 0.0
    highest_degree: str = ""         # bachelors | masters | phd
    work_authorization: list[str] = field(default_factory=lambda: ["India"])
    notice_period_days: int = 0
    willing_to_learn: list[str] = field(default_factory=list)


@dataclass
class Profile:
    name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    headline: str = ""
    narrative: str = ""
    links: dict[str, str] = field(default_factory=dict)
    education: list[dict[str, Any]] = field(default_factory=list)
    skills: dict[str, Skill] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    preferences: Preferences = field(default_factory=Preferences)
    constraints: Constraints = field(default_factory=Constraints)

    def skill(self, key: str) -> Skill | None:
        return self.skills.get(key)

    def level_of(self, key: str) -> Level:
        s = self.skills.get(key)
        return s.level if s else Level.NONE

    def evidence_for(self, key: str) -> list[Evidence]:
        s = self.skills.get(key)
        if not s:
            return []
        return [self.evidence[e] for e in s.evidence if e in self.evidence]

    def domains(self) -> set[str]:
        out: set[str] = set(self.preferences.domains)
        for ev in self.evidence.values():
            out.update(ev.domains)
        return out


# --------------------------------------------------------------------------
# Opportunities
# --------------------------------------------------------------------------


@dataclass
class Company:
    key: str
    name: str
    website: str = ""
    careers_url: str = ""
    ats: dict[str, str] = field(default_factory=dict)   # {"provider": "lever", "slug": "x"}
    hq: str = ""
    stage: str = ""
    domains: list[str] = field(default_factory=list)
    about: str = ""
    founders: list[dict[str, str]] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)    # "iit_founder", "govt_backed", ...
    outreach_modes: list[str] = field(default_factory=list)
    source: str = "registry"


@dataclass
class Requirement:
    skill: str                      # canonical key, or a pseudo-key like "years_experience"
    label: str
    necessity: Necessity = Necessity.REQUIRED
    raw: str = ""

    @property
    def weight(self) -> float:
        return self.necessity.weight


@dataclass
class Job:
    id: str
    company_key: str
    company_name: str
    title: str
    url: str = ""
    location: str = ""
    remote: bool = False
    description: str = ""
    employment_type: str = "full_time"
    salary_text: str = ""
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    posted_at: str = ""
    source: str = ""
    requirements: list[Requirement] = field(default_factory=list)
    min_years: float | None = None
    degree_required: str = ""
    seniority: str = ""

    @staticmethod
    def make_id(company_key: str, title: str, url: str, location: str = "") -> str:
        raw = "|".join([company_key.lower(), title.lower().strip(), url or location.lower()])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Person:
    key: str
    company_key: str
    name: str
    title: str = ""
    role_class: str = ""            # recruiter | hiring_manager | ml_lead | founder | cto
    linkedin: str = ""
    email: str = ""
    email_status: str = "unknown"   # verified | published | pattern_guess | unknown
    email_confidence: float = 0.0
    source: str = ""
    notes: str = ""

    @property
    def is_safe_to_email(self) -> bool:
        return self.email_status in {"verified", "published"} and bool(self.email)


# --------------------------------------------------------------------------
# Assessment / output
# --------------------------------------------------------------------------


@dataclass
class RequirementMatch:
    requirement: Requirement
    your_level: Level
    score: float                    # 0..1
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def is_gap(self) -> bool:
        return self.requirement.necessity is Necessity.REQUIRED and self.score < 0.5


@dataclass
class Assessment:
    job_id: str
    eligibility: float              # 0..100 - can you realistically apply
    technical_match: float          # 0..100 - can you do the work
    domain_fit: float               # 0..100 - does the company's problem match your work
    overall: float                  # 0..100
    band: Band
    mode: Mode
    verdict: str
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    matches: list[RequirementMatch] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def should_apply(self) -> bool:
        return self.band is not Band.SKIP


@dataclass
class Application:
    job_id: str
    status: Status = Status.NOT_CONTACTED
    resume_path: str = ""
    person_key: str = ""
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""
    followup_body: str = ""
    updated_at: str = field(default_factory=lambda: date.today().isoformat())
    notes: str = ""


def to_jsonable(obj: Any) -> Any:
    """dataclass/Enum aware serializer used by the store and exporters."""
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj))
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return obj


def dumps(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), ensure_ascii=False, indent=2, sort_keys=True)
