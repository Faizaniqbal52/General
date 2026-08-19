"""Single-file HTML dashboard: the table on the left, the full application
package on the right. No network, no build step - open the file in a browser."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

from ..pipeline import Package
from .rows import package_rows

_CSS = """
:root { --bg:#f6f7f9; --panel:#fff; --ink:#15181d; --muted:#5c626d; --line:#e2e5ea;
        --accent:#1f6feb; --aplus:#0f7b3f; --a:#2e7d32; --b:#a06a00; --c:#8a5a2b; --skip:#6b7280; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0f1115; --panel:#171a20; --ink:#e8eaee; --muted:#9aa1ad; --line:#262b33;
          --accent:#5b9bff; --aplus:#4ade80; --a:#69d38a; --b:#e3b341; --c:#d99a5b; --skip:#8b939f; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 -apple-system,BlinkMacSystemFont,
       "Segoe UI",Roboto,Ubuntu,sans-serif; }
header { padding:16px 20px; border-bottom:1px solid var(--line); background:var(--panel);
         display:flex; gap:16px; align-items:baseline; flex-wrap:wrap; position:sticky; top:0; z-index:5; }
h1 { font-size:17px; margin:0; letter-spacing:.2px; }
.stats { color:var(--muted); font-size:12.5px; }
.wrap { display:grid; grid-template-columns: minmax(420px, 1.15fr) minmax(360px, 1fr); gap:14px;
        padding:14px; align-items:start; }
@media (max-width: 980px) { .wrap { grid-template-columns:1fr; } }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.controls { display:flex; gap:8px; padding:10px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
input[type=search], select { background:transparent; color:var(--ink); border:1px solid var(--line);
       border-radius:7px; padding:6px 9px; font-size:13px; }
input[type=search] { flex:1; min-width:150px; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); font-size:13px;
         vertical-align:top; }
th { font-size:11px; text-transform:uppercase; letter-spacing:.6px; color:var(--muted); font-weight:600;
     position:sticky; top:0; background:var(--panel); cursor:pointer; }
tbody tr { cursor:pointer; }
tbody tr:hover { background:color-mix(in srgb, var(--accent) 8%, transparent); }
tbody tr.active { background:color-mix(in srgb, var(--accent) 14%, transparent); }
.badge { display:inline-block; padding:1px 7px; border-radius:999px; font-size:11px; font-weight:700;
         border:1px solid currentColor; }
.p-Aplus { color:var(--aplus); } .p-A { color:var(--a); } .p-B { color:var(--b); }
.p-C { color:var(--c); } .p-SKIP { color:var(--skip); }
.new { color:var(--accent); font-size:11px; font-weight:700; }
.detail { padding:14px 16px; max-height:calc(100vh - 120px); overflow:auto; }
.detail h2 { font-size:16px; margin:0 0 2px; }
.detail .sub { color:var(--muted); font-size:12.5px; margin-bottom:12px; }
.scores { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.score { border:1px solid var(--line); border-radius:8px; padding:6px 10px; min-width:82px; }
.score b { display:block; font-size:17px; } .score span { font-size:11px; color:var(--muted); }
section { margin-bottom:14px; }
section h3 { font-size:11.5px; text-transform:uppercase; letter-spacing:.7px; color:var(--muted);
             margin:0 0 6px; }
pre { white-space:pre-wrap; background:var(--bg); border:1px solid var(--line); border-radius:8px;
      padding:10px; font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; margin:0; }
ul { margin:0; padding-left:18px; } li { margin-bottom:2px; }
.row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }
button, a.btn { background:var(--accent); color:#fff; border:0; border-radius:7px; padding:6px 11px;
        font-size:12.5px; cursor:pointer; text-decoration:none; display:inline-block; }
a.btn.ghost, button.ghost { background:transparent; color:var(--accent); border:1px solid var(--accent); }
.warn { color:#b45309; font-size:12.5px; }
.mono { font:12.5px ui-monospace,Menlo,monospace; }
.empty { padding:30px; color:var(--muted); text-align:center; }
"""

_JS = """
const DATA = __DATA__;
let sortKey = null, sortDir = 1, selected = 0;
const $ = (sel) => document.querySelector(sel);
const esc = (s) => (s ?? "").toString().replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]));

function visible() {
  const q = $("#q").value.toLowerCase().trim();
  const band = $("#band").value, status = $("#status").value, mode = $("#mode").value;
  let rows = DATA.filter(r =>
    (!band || r.priority === band) &&
    (!status || r.status === status) &&
    (!mode || r.mode === mode) &&
    (!q || (r.company + " " + r.role + " " + r.why + " " + r.location).toLowerCase().includes(q)));
  if (sortKey) rows = rows.slice().sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * sortDir;
  });
  return rows;
}

function renderTable() {
  const rows = visible();
  $("#count").textContent = rows.length + " shown";
  const body = rows.map((r) => `
    <tr data-i="${DATA.indexOf(r)}" class="${DATA.indexOf(r) === selected ? "active" : ""}">
      <td><span class="badge p-${r.priority.replace("+", "plus")}">${esc(r.priority)}</span>
          ${r.new ? '<div class="new">NEW</div>' : ""}</td>
      <td><b>${esc(r.company)}</b><div style="color:var(--muted);font-size:12px">${esc(r.location)}</div></td>
      <td>${esc(r.role)}<div style="color:var(--muted);font-size:12px">${esc(r.mode)}${r.salary ? " · " + esc(r.salary) : ""}</div></td>
      <td><b>${r.overall}</b><div style="color:var(--muted);font-size:11.5px">t${r.technical} · e${r.eligibility}</div></td>
      <td>${esc(r.status.replace(/_/g, " "))}</td>
    </tr>`).join("");
  $("#tbody").innerHTML = body || '<tr><td colspan="5" class="empty">Nothing matches these filters.</td></tr>';
  document.querySelectorAll("#tbody tr[data-i]").forEach(tr =>
    tr.addEventListener("click", () => { selected = +tr.dataset.i; renderTable(); renderDetail(); }));
}

function copyBlock(text, label) {
  return `<button class="ghost" data-copy="${esc(text).replace(/\\n/g, "&#10;")}">${label}</button>`;
}

function renderDetail() {
  const r = DATA[selected];
  if (!r) { $("#detail").innerHTML = '<div class="empty">Select a row.</div>'; return; }
  const searches = (r.searches || "").split("\\n").filter(Boolean)
    .map(s => `<li><a href="https://www.google.com/search?q=${encodeURIComponent(s)}" target="_blank" rel="noopener" class="mono">${esc(s)}</a></li>`).join("");
  $("#detail").innerHTML = `
    <h2>${esc(r.role)}</h2>
    <div class="sub">${esc(r.company)} · ${esc(r.location)}${r.salary ? " · " + esc(r.salary) : ""} · route: ${esc(r.mode)}</div>
    <div class="scores">
      <div class="score"><b>${r.overall}</b><span>overall</span></div>
      <div class="score"><b>${r.technical}</b><span>technical</span></div>
      <div class="score"><b>${r.eligibility}</b><span>eligibility</span></div>
      <div class="score"><b>${r.domain}</b><span>domain fit</span></div>
    </div>
    <section><h3>Verdict</h3><pre>${esc(r.verdict)}</pre></section>
    <section><h3>Why you match</h3><p>${esc(r.why) || "-"}</p>
      <h3 style="margin-top:8px">Gaps</h3><p>${esc(r.gaps)}</p></section>
    <section><h3>Contact</h3>
      <p>${esc(r.contact_name) || "not identified yet"}${r.contact_title ? " · " + esc(r.contact_title) : ""}<br>
      ${r.contact_email ? `<span class="mono">${esc(r.contact_email)}</span> <span class="warn">(${esc(r.contact_email_status)})</span>` : '<span class="warn">no address yet</span>'}
      ${r.contact_link ? `<br><a href="${esc(r.contact_link)}" target="_blank" rel="noopener">${esc(r.contact_link)}</a>` : ""}</p>
      ${searches ? `<h3 style="margin-top:8px">Find a human</h3><ul>${searches}</ul>` : ""}
    </section>
    <section><h3>Email</h3>
      <div class="row">${copyBlock(r.email_subject, "Copy subject")}${copyBlock(r.email_body, "Copy body")}
      ${r.contact_email ? `<a class="btn" href="mailto:${encodeURIComponent(r.contact_email)}?subject=${encodeURIComponent(r.email_subject)}&body=${encodeURIComponent(r.email_body)}">Open in mail client</a>` : ""}</div>
      <pre>${esc(r.email_subject)}\n\n${esc(r.email_body)}</pre></section>
    <section><h3>LinkedIn note</h3><div class="row">${copyBlock(r.linkedin_note, "Copy note")}</div>
      <pre>${esc(r.linkedin_note)}</pre></section>
    <section><h3>Files & links</h3>
      <div class="row">
        ${r.resume ? `<a class="btn ghost" href="${esc(r.resume)}" target="_blank" rel="noopener">Tailored CV</a>` : ""}
        ${r.job_url ? `<a class="btn ghost" href="${esc(r.job_url)}" target="_blank" rel="noopener">Job posting</a>` : ""}
      </div>
      <p style="color:var(--muted);font-size:12px">Status: ${esc(r.status)} · first seen ${esc(r.first_seen)} · source ${esc(r.source)}<br>
      Update status with: <span class="mono">python -m jobpilot status "${esc(r.company)}" applied</span></p>
    </section>`;
  document.querySelectorAll("[data-copy]").forEach(btn => btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(btn.dataset.copy); btn.textContent = "Copied"; }
    catch { btn.textContent = "Select the text below"; }
    setTimeout(() => renderDetail(), 1200);
  }));
}

document.querySelectorAll("th[data-key]").forEach(th => th.addEventListener("click", () => {
  const key = th.dataset.key;
  sortDir = sortKey === key ? -sortDir : (key === "overall" ? -1 : 1);
  sortKey = key; renderTable();
}));
["q", "band", "status", "mode"].forEach(id =>
  $("#" + id).addEventListener("input", () => { renderTable(); }));
renderTable(); renderDetail();
"""


def write_dashboard(packages: list[Package], path: str | Path, title: str = "JobPilot") -> Path:
    rows = package_rows(packages)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # resume links must resolve relative to the dashboard file itself, not to
    # whatever directory the run happened to start in
    for row in rows:
        if row.get("resume"):
            try:
                row["resume"] = os.path.relpath(Path(row["resume"]).resolve(),
                                                path.parent.resolve())
            except ValueError:                     # different drive on Windows
                row["resume"] = Path(row["resume"]).resolve().as_uri()

    bands: dict[str, int] = {}
    for row in rows:
        bands[row["priority"]] = bands.get(row["priority"], 0) + 1
    stat_bits = [f"{count} {band}" for band, count in
                 sorted(bands.items(), key=lambda kv: kv[0])]
    new_count = sum(1 for row in rows if row["new"])

    options = lambda values: "".join(  # noqa: E731 - tiny local helper
        f'<option value="{html.escape(v)}">{html.escape(v)}</option>' for v in values)
    statuses = sorted({row["status"] for row in rows})
    modes = sorted({row["mode"] for row in rows})

    data = json.dumps(rows, ensure_ascii=False)
    js = _JS.replace("__DATA__", data)

    return _write(path, f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <div class="stats">{len(rows)} opportunities · {' · '.join(stat_bits)} · {new_count} new this run</div>
  <div class="stats" id="count"></div>
</header>
<div class="wrap">
  <div class="card">
    <div class="controls">
      <input id="q" type="search" placeholder="Search company, role, location…">
      <select id="band"><option value="">All priorities</option>{options(['A+', 'A', 'B', 'C', 'SKIP'])}</select>
      <select id="mode"><option value="">All routes</option>{options(modes)}</select>
      <select id="status"><option value="">All statuses</option>{options(statuses)}</select>
    </div>
    <table>
      <thead><tr>
        <th data-key="priority">Priority</th><th data-key="company">Company</th>
        <th data-key="role">Role</th><th data-key="overall">Score</th><th data-key="status">Status</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <div class="card"><div class="detail" id="detail"></div></div>
</div>
<script>{js}</script>
</body></html>
""")


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path
