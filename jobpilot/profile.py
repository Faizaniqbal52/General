"""Load and validate the master profile - your 'professional brain'.

The profile is the single source of truth. Every claim the rest of the system
makes must trace back to something in here, which is why loading is strict:
a skill that points at an evidence id which does not exist is an error, not a
warning, and a `strong` skill with no evidence at all is reported so you can
fix it before it ends up on a resume.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import Constraints, Evidence, Level, Preferences, Profile, Skill
from .parsing.taxonomy import canonical_skill, label_of

try:  # PyYAML is the nicer authoring format but not strictly required
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised only without PyYAML
    yaml = None


class ProfileError(ValueError):
    """Raised when the master profile cannot be trusted."""


EVIDENCE_SECTIONS = {
    "projects": "project",
    "experience": "experience",
    "publications": "publication",
    "open_source": "repo",
    "certifications": "cert",
}


def _read(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise ProfileError(
                f"{path} is YAML but PyYAML is not installed. "
                "Install PyYAML or convert the profile to JSON."
            )
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: expected a mapping at the top level")
    return data


def _evidence_from(section: str, kind: str, items: Any) -> list[Evidence]:
    out: list[Evidence] = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            raise ProfileError(f"{section}[{i}] must be a mapping")
        name = item.get("name") or item.get("title") or item.get("company") or ""
        if not name:
            raise ProfileError(f"{section}[{i}] needs a name/title")
        ident = item.get("id") or _slug(name)
        skills = []
        for raw in item.get("skills", []) or []:
            key = canonical_skill(str(raw))
            skills.append(key or str(raw).strip().lower().replace(" ", "_"))
        out.append(
            Evidence(
                id=ident,
                kind=kind,
                name=name,
                summary=item.get("summary", "") or item.get("description", ""),
                role=item.get("role", "") or item.get("position", ""),
                period=str(item.get("period", "") or item.get("dates", "")),
                highlights=[str(h) for h in item.get("highlights", []) or []],
                skills=skills,
                domains=[str(d).lower().replace(" ", "_") for d in item.get("domains", []) or []],
                metrics=[str(m) for m in item.get("metrics", []) or []],
                links=[str(u) for u in _as_list(item.get("links") or item.get("link"))],
            )
        )
    return out


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in text]
    return "".join(keep).strip("_").replace("__", "_")


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    if not path.exists():
        raise ProfileError(f"profile not found: {path}")
    data = _read(path)

    identity = data.get("identity", data)
    name = identity.get("name")
    if not name:
        raise ProfileError("identity.name is required")

    evidence: dict[str, Evidence] = {}
    for section, kind in EVIDENCE_SECTIONS.items():
        for item in _evidence_from(section, kind, data.get(section)):
            if item.id in evidence:
                raise ProfileError(f"duplicate evidence id: {item.id}")
            evidence[item.id] = item

    skills: dict[str, Skill] = {}
    for i, raw in enumerate(data.get("skills", []) or []):
        if isinstance(raw, str):
            raw = {"name": raw, "level": "intermediate"}
        if not isinstance(raw, dict):
            raise ProfileError(f"skills[{i}] must be a string or a mapping")
        source_name = raw.get("name") or raw.get("skill") or ""
        if not source_name:
            raise ProfileError(f"skills[{i}] needs a name")
        key = canonical_skill(source_name) or _slug(source_name)
        ev = [str(e) for e in _as_list(raw.get("evidence"))]
        missing = [e for e in ev if e not in evidence]
        if missing:
            raise ProfileError(
                f"skill '{source_name}' cites unknown evidence {missing}. "
                f"Known ids: {sorted(evidence)[:8]}..."
            )
        skill = Skill(
            name=key,
            label=label_of(key) if key in _known_labels() else str(source_name),
            level=Level.parse(raw.get("level")),
            evidence=ev,
            note=str(raw.get("note", "")),
        )
        if key in skills:  # keep the strongest declaration, merge the evidence
            prior = skills[key]
            skill = replace(
                skill,
                level=max((prior.level, skill.level), key=lambda l: l.weight),
                evidence=sorted(set(prior.evidence) | set(skill.evidence)),
            )
        skills[key] = skill

    # skills implied by evidence but never declared are added at basic level, so
    # that a project that clearly used Docker still counts for matching.
    for ev_item in evidence.values():
        for key in ev_item.skills:
            if key not in skills:
                skills[key] = Skill(
                    name=key,
                    label=label_of(key),
                    level=Level.BASIC,
                    evidence=[ev_item.id],
                    note="inferred from project evidence",
                )
            elif ev_item.id not in skills[key].evidence:
                skills[key].evidence.append(ev_item.id)

    prefs_raw = data.get("preferences", {}) or {}
    preferences = Preferences(
        roles=[str(r) for r in prefs_raw.get("roles", []) or []],
        locations=[str(l) for l in prefs_raw.get("locations", []) or []],
        remote_ok=bool(prefs_raw.get("remote_ok", True)),
        onsite_ok=bool(prefs_raw.get("onsite_ok", True)),
        relocate_ok=bool(prefs_raw.get("relocate_ok", False)),
        employment_types=[str(e) for e in prefs_raw.get("employment_types", []) or
                          ["full_time", "internship"]],
        min_salary_lpa=_maybe_float(prefs_raw.get("min_salary_lpa")),
        domains=[str(d).lower().replace(" ", "_") for d in prefs_raw.get("domains", []) or []],
        avoid=[str(a).lower() for a in prefs_raw.get("avoid", []) or []],
    )

    cons_raw = data.get("constraints", {}) or {}
    constraints = Constraints(
        graduation_year=_maybe_int(cons_raw.get("graduation_year")),
        years_experience=float(cons_raw.get("years_experience") or 0.0),
        highest_degree=str(cons_raw.get("highest_degree", "")).lower(),
        work_authorization=[str(w) for w in cons_raw.get("work_authorization", []) or ["India"]],
        notice_period_days=int(cons_raw.get("notice_period_days") or 0),
        willing_to_learn=[str(w) for w in cons_raw.get("willing_to_learn", []) or []],
    )

    return Profile(
        name=str(name),
        email=str(identity.get("email", "")),
        phone=str(identity.get("phone", "")),
        location=str(identity.get("location", "")),
        headline=str(identity.get("headline", "")),
        narrative=str(data.get("narrative", "")).strip(),
        links={str(k): str(v) for k, v in (identity.get("links", {}) or {}).items()},
        education=[dict(e) for e in data.get("education", []) or []],
        skills=skills,
        evidence=evidence,
        preferences=preferences,
        constraints=constraints,
    )


def _known_labels() -> set[str]:
    from .parsing.taxonomy import SKILLS
    return set(SKILLS)


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def audit(profile: Profile) -> list[str]:
    """Non-fatal problems worth fixing before the agent speaks for you."""
    notes: list[str] = []
    for skill in profile.skills.values():
        if skill.level in {Level.STRONG, Level.INTERMEDIATE} and not skill.is_evidenced:
            notes.append(
                f"skill '{skill.label}' is declared {skill.level.value} but has no evidence; "
                "it will be down-weighted and kept off tailored resumes"
            )
    for ev in profile.evidence.values():
        if not ev.skills:
            notes.append(f"evidence '{ev.id}' lists no skills, so it can never be selected")
        if not ev.highlights and not ev.summary:
            notes.append(f"evidence '{ev.id}' has no summary or highlights to put on a resume")
    if not profile.narrative:
        notes.append("no narrative set - outreach emails will be more generic")
    if not profile.preferences.roles:
        notes.append("preferences.roles is empty - discovery will use default AI/software roles")
    return notes
