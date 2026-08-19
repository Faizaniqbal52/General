"""Render a tailored resume as Markdown or as print-ready HTML.

The HTML is one self-contained A4 page - open it in a browser and print to PDF.
No external CSS, no fonts to download, nothing that breaks when a recruiter
opens it on a different machine.
"""

from __future__ import annotations

import html

from .tailor import ResumeItem, TailoredResume


def _contact_line(resume: TailoredResume) -> str:
    order = ["email", "phone", "location", "github", "linkedin", "huggingface", "website", "scholar"]
    parts = [resume.contact[k] for k in order if resume.contact.get(k)]
    parts += [v for k, v in resume.contact.items() if k not in order]
    return " · ".join(parts)


def _md_item(item: ResumeItem) -> list[str]:
    head = f"**{item.name}**"
    meta = " · ".join(p for p in (item.role, item.period) if p)
    lines = [f"{head}{(' — ' + meta) if meta else ''}"]
    if item.summary and item.summary not in item.highlights:
        lines.append(f"{item.summary}")
    lines += [f"- {h}" for h in item.highlights]
    if item.links:
        lines.append("- " + " · ".join(item.links))
    lines.append("")
    return lines


def render_markdown(resume: TailoredResume, *, include_notes: bool = False) -> str:
    out: list[str] = [f"# {resume.name}"]
    if resume.headline:
        out.append(f"*{resume.headline}*")
    contact = _contact_line(resume)
    if contact:
        out.append(contact)
    out.append("")

    if resume.summary:
        out += ["## Summary", resume.summary, ""]

    if resume.skill_groups:
        out.append("## Skills")
        for label, items in resume.skill_groups:
            out.append(f"**{label}:** {', '.join(items)}")
        out.append("")

    for title, items in (("Experience", resume.experience),
                         ("Selected projects", resume.projects),
                         ("Publications", resume.publications)):
        if not items:
            continue
        out.append(f"## {title}")
        for item in items:
            out += _md_item(item)

    if resume.education:
        out.append("## Education")
        for row in resume.education:
            head = " ".join(p for p in (row.get("degree", ""), row.get("field", "")) if p)
            meta = " · ".join(p for p in (row.get("institution", ""), row.get("period", "")) if p)
            out.append(f"**{head}**{(' — ' + meta) if meta else ''}")
            if row.get("notes"):
                out.append(row["notes"])
        out.append("")

    if resume.achievements:
        out.append("## Recognition")
        out += [f"- {line}" for line in resume.achievements]
        out.append("")

    if include_notes:
        out.append("---")
        out.append(f"<!-- tailored for {resume.job_title} at {resume.company_name} -->")
        for note in resume.footnotes:
            out.append(f"<!-- {note} -->")
        if resume.excluded:
            out.append(f"<!-- held back: {'; '.join(resume.excluded)} -->")
    return "\n".join(out).rstrip() + "\n"


_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f3f4f6; font-family: "Iowan Old Style", Georgia, "Times New Roman", serif;
       color: #16181d; line-height: 1.42; }
.page { width: 210mm; min-height: 297mm; margin: 12px auto; padding: 16mm 16mm 14mm;
        background: #fff; box-shadow: 0 1px 6px rgba(0,0,0,.14); }
h1 { font-size: 25px; margin: 0 0 2px; letter-spacing: .2px; }
.headline { font-size: 12.5px; color: #45484f; margin: 0 0 4px; font-style: italic; }
.contact { font-size: 10.5px; color: #33363c; margin: 0 0 12px; word-spacing: .5px; }
h2 { font-size: 11.5px; text-transform: uppercase; letter-spacing: 1.1px; color: #1f2937;
     border-bottom: 1px solid #cfd3da; padding-bottom: 3px; margin: 14px 0 7px; }
p, li { font-size: 11.2px; margin: 0 0 3px; }
.summary { font-size: 11.4px; margin-bottom: 4px; }
.item { margin-bottom: 9px; }
.item-head { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.item-name { font-weight: 700; font-size: 11.8px; }
.item-meta { font-size: 10.2px; color: #565b64; white-space: nowrap; }
.item-sub { font-size: 10.6px; color: #3d414a; font-style: italic; margin-bottom: 2px; }
ul { margin: 2px 0 0 16px; padding: 0; }
.skills p { margin-bottom: 2px; }
.skills b { font-weight: 700; }
a { color: #16181d; text-decoration: none; border-bottom: .5px dotted #9aa0aa; }
@media print {
  body { background: #fff; }
  .page { width: auto; min-height: auto; margin: 0; padding: 12mm; box-shadow: none; }
  @page { size: A4; margin: 0; }
}
"""


def _h(text: str) -> str:
    return html.escape(text or "", quote=False)


def _html_item(item: ResumeItem) -> str:
    meta = " · ".join(p for p in (item.role, item.period) if p)
    bullets = "".join(f"<li>{_h(b)}</li>" for b in item.highlights)
    links = ""
    if item.links:
        links = "<div class='item-sub'>" + " · ".join(
            f"<a href='{_h(u)}'>{_h(u)}</a>" for u in item.links) + "</div>"
    sub = f"<div class='item-sub'>{_h(item.summary)}</div>" if item.summary else ""
    return (f"<div class='item'><div class='item-head'><span class='item-name'>{_h(item.name)}</span>"
            f"<span class='item-meta'>{_h(meta)}</span></div>{sub}"
            f"{'<ul>' + bullets + '</ul>' if bullets else ''}{links}</div>")


def render_html(resume: TailoredResume) -> str:
    blocks: list[str] = []
    if resume.summary:
        blocks.append(f"<h2>Summary</h2><p class='summary'>{_h(resume.summary)}</p>")
    if resume.skill_groups:
        rows = "".join(f"<p><b>{_h(label)}:</b> {_h(', '.join(items))}</p>"
                       for label, items in resume.skill_groups)
        blocks.append(f"<h2>Skills</h2><div class='skills'>{rows}</div>")
    for title, items in (("Experience", resume.experience),
                         ("Selected projects", resume.projects),
                         ("Publications", resume.publications)):
        if items:
            blocks.append(f"<h2>{title}</h2>" + "".join(_html_item(i) for i in items))
    if resume.education:
        rows = []
        for row in resume.education:
            head = " ".join(p for p in (row.get("degree", ""), row.get("field", "")) if p)
            meta = " · ".join(p for p in (row.get("institution", ""), row.get("period", "")) if p)
            notes = (f"<div class='item-sub'>{_h(row['notes'])}</div>" if row.get("notes") else "")
            rows.append(f"<div class='item'><div class='item-head'>"
                        f"<span class='item-name'>{_h(head)}</span>"
                        f"<span class='item-meta'>{_h(meta)}</span></div>{notes}</div>")
        blocks.append("<h2>Education</h2>" + "".join(rows))

    if resume.achievements:
        items = "".join(f"<li>{_h(line)}</li>" for line in resume.achievements)
        blocks.append(f"<h2>Recognition</h2><ul>{items}</ul>")

    contact = _contact_line(resume)
    title = f"{resume.name} — {resume.job_title} — {resume.company_name}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h(title)}</title><style>{_CSS}</style></head>
<body><div class="page">
<h1>{_h(resume.name)}</h1>
{f'<p class="headline">{_h(resume.headline)}</p>' if resume.headline else ''}
<p class="contact">{_h(contact)}</p>
{''.join(blocks)}
</div></body></html>
"""
