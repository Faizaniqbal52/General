"""Draft the outreach. Assembled from your profile - never sent automatically.

Four registers, because writing to a recruiter about a posting and writing to a
founder who has no posting are not the same email:

  direct    - there is a posting; be specific about it and about your evidence
  recruiter - no exact posting; ask about the team, lead with fit
  founder   - small team; lead with the work, offer to be useful
  technical - go to the ML/research lead with a technical note, not a CV blast

Every draft is text you can edit. Nothing here contacts anybody.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Assessment, Company, Evidence, Job, Mode, Person, Profile
from ..textutil import first_sentence, truncate


@dataclass
class OutreachDraft:
    mode: str
    subject: str
    body: str
    short_body: str
    linkedin_note: str
    linkedin_message: str
    followup_subject: str
    followup_body: str
    to: str = ""
    to_name: str = ""
    to_status: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def as_mailto(self) -> str:
        from urllib.parse import quote
        if not self.to:
            return ""
        return f"mailto:{self.to}?subject={quote(self.subject)}&body={quote(self.body)}"


def _greeting(person: Person | None) -> str:
    if person and person.name and person.role_class != "inbox":
        first = person.name.split()[0]
        return f"Hi {first},"
    return "Hello,"


def _top_evidence(profile: Profile, assessment: Assessment | None, limit: int = 2) -> list[Evidence]:
    ids = list(assessment.evidence_ids) if assessment else []
    seen: list[Evidence] = []
    for eid in ids:
        ev = profile.evidence.get(eid)
        if ev and ev not in seen:
            seen.append(ev)
        if len(seen) >= limit:
            break
    if not seen:
        seen = [ev for ev in profile.evidence.values() if ev.kind == "project"][:limit]
    return seen


def _evidence_line(ev: Evidence) -> str:
    detail = ev.highlights[0] if ev.highlights else first_sentence(ev.summary, 150)
    detail = detail[0].lower() + detail[1:] if detail else ""
    return f"{ev.name} - {detail.rstrip('.')}" if detail else ev.name


def _links_line(profile: Profile) -> str:
    order = ["github", "huggingface", "website", "scholar", "linkedin"]
    links = [profile.links[k] for k in order if profile.links.get(k)]
    return " · ".join(links[:3])


def _strength_phrase(assessment: Assessment | None, limit: int = 3) -> str:
    if not assessment or not assessment.strengths:
        return ""
    items = assessment.strengths[:limit]
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# company blurbs usually start with a verb ("Builds foundational models ...").
# Stripped so the hook can be dropped into "X is working on <hook>".
_LEADING_VERB = re.compile(
    r"^(?:builds?|building|works? on|working on|develops?|developing|creates?|creating|"
    r"provides?|providing|makes?|making|is|are|offers?|offering)\s+", re.IGNORECASE)


# words that must keep their capital when a hook is dropped mid-sentence
_KEEP_CAPS = {"indian", "india", "bharat", "kashmiri", "hindi", "english", "asian", "european"}


def _decap(text: str) -> str:
    """Lowercase the first letter unless it is a proper noun or an acronym."""
    if not text:
        return text
    match = re.match(r"[A-Za-z]+", text)
    first = match.group(0) if match else ""
    if not first or first.isupper() or first.lower() in _KEEP_CAPS:
        return text
    return text[0].lower() + text[1:]


def _company_hook(company: Company | None, job: Job | None) -> str:
    text = ""
    if company and company.about:
        text = first_sentence(company.about, 180)
    elif job and job.description:
        text = first_sentence(job.description, 160)
    return _LEADING_VERB.sub("", text).rstrip(".").strip()


def build_drafts(profile: Profile, job: Job, assessment: Assessment,
                 company: Company | None = None, person: Person | None = None) -> OutreachDraft:
    mode = assessment.mode
    greeting = _greeting(person)
    evidence = _top_evidence(profile, assessment)
    ev_lines = [f"- {_evidence_line(ev)}" for ev in evidence]
    strengths = _strength_phrase(assessment)
    hook = _company_hook(company, job)
    links = _links_line(profile)
    company_name = company.name if company else job.company_name
    sign = f"\n\n{profile.name}" + (f"\n{links}" if links else "") + \
           (f"\n{profile.email}" if profile.email else "")

    if mode is Mode.DIRECT:
        subject = f"{job.title} - {profile.name}"
        opening = (f"I came across the {job.title} opening at {company_name}"
                   + (f" and the part about {_decap(hook)} is close to what I have been building.\n"
                      if hook else ".\n"))
        ask = ("I have applied through the posting. If it would help, I am happy to walk through "
               "the training and evaluation setup for any of the above.")
    elif mode is Mode.RECRUITER:
        subject = f"{profile.headline or 'AI/ML engineer'} interested in {company_name}"
        opening = (f"I did not see a posting that matches exactly, but I wanted to reach out about "
                   f"{company_name}"
                   + (f" - {_decap(hook)} overlaps closely with my own work.\n" if hook else ".\n"))
        ask = ("If there is a team where this would be useful - engineering, research or an "
               "internship - I would like to be considered.")
    elif mode is Mode.FOUNDER:
        subject = f"{company_name} - {truncate(profile.headline or 'AI work', 60)}"
        opening = (f"I have been following what you are building at {company_name}"
                   + (f", particularly {_decap(hook)}.\n" if hook else ".\n"))
        ask = ("If you are hiring - or would take someone who is willing to start on a hard, "
               "unglamorous piece of it - I would like to talk. Happy to do a scoped piece of "
               "work first so you can judge the output rather than the CV.")
    else:  # TECHNICAL
        subject = f"{job.title or 'Technical note'} - {strengths or 'ML work'} - {profile.name}"
        opening = (f"I am writing to you rather than to a recruiting address because the work is "
                   f"the point. {company_name}"
                   + (f" is working on {_decap(hook)}, which is the same problem space as my own "
                      "projects.\n" if hook else " is close to what I work on.\n"))
        ask = ("If there is an opening on the team, or a research/engineering internship, I would "
               "like to be considered. I am also glad to just send the evaluation results if "
               "they are useful to you.")

    context = first_sentence(profile.narrative, 320)
    strengths_line = (f"Where I think I would be immediately useful: {strengths}.\n"
                      if strengths else "")

    body = (f"{greeting}\n\n"
            f"{opening}\n"
            f"{context}\n\n"
            f"{'What is' if len(ev_lines) == 1 else 'Two things that are'} most relevant here:\n"
            + "\n".join(ev_lines)
            + f"\n\n{strengths_line}{ask}"
            + (f"\n\nWork: {links}" if links else "")
            + sign)

    short_body = (f"{greeting}\n\n"
                  f"{opening.strip()} "
                  f"{(evidence[0].name + ': ' + first_sentence(evidence[0].summary, 140)) if evidence else ''}\n\n"
                  f"{ask}"
                  + (f"\n\n{links}" if links else "")
                  + sign)

    note_core = (f"I work on {strengths or 'applied AI'} - "
                 f"{evidence[0].name if evidence else 'projects'} is the closest to what "
                 f"{company_name} is doing. Would like to connect about "
                 f"{'the ' + job.title + ' role' if mode is Mode.DIRECT else 'your team'}.")
    linkedin_note = truncate(note_core, 290)

    linkedin_message = (f"{greeting}\n\n{opening.strip()}\n\n"
                        + "\n".join(ev_lines)
                        + f"\n\n{ask}"
                        + (f"\n\n{links}" if links else ""))

    followup_subject = f"Re: {subject}"
    followup_body = (f"{greeting}\n\n"
                     f"Following up on my note about "
                     f"{job.title if mode is Mode.DIRECT else company_name}. "
                     "I know inboxes fill up, so this is just a short nudge - I remain very "
                     "interested, and I am happy to share the code and evaluation results for "
                     f"{evidence[0].name if evidence else 'my projects'} if that is more useful "
                     "than a CV."
                     + sign)

    warnings: list[str] = []
    to = person.email if person else ""
    if person and person.email and not person.is_safe_to_email:
        warnings.append(
            f"{person.email} is a {person.email_status.replace('_', ' ')} - confirm it before sending")
    if not person:
        warnings.append("no contact identified yet - run the searches in the contact plan first")
    if assessment.band.value == "SKIP":
        warnings.append("this opportunity is marked SKIP; the draft exists only for completeness")

    return OutreachDraft(
        mode=mode.value,
        subject=subject,
        body=body,
        short_body=short_body,
        linkedin_note=linkedin_note,
        linkedin_message=linkedin_message,
        followup_subject=followup_subject,
        followup_body=followup_body,
        to=to,
        to_name=person.name if person else "",
        to_status=person.email_status if person else "unknown",
        warnings=warnings,
    )
