# JobPilot

A personal, evidence-backed job-hunting agent for AI/ML and software roles in India.

You give it one file describing everything you can actually do and prove. It finds
openings, decides whether each one is worth your time, writes a resume tailored to
that specific role out of your real evidence, tells you which human to approach and
how to find them, drafts the message, and puts the whole thing in a sheet and a
dashboard. You review and send. It never sends anything itself.

It also treats *companies with no posting* as first-class opportunities - the Indian
AI ecosystem has a lot of small research-led teams where the right route in is a
technical note to the person doing the work, not an application form.

```
profile.yaml ──▶ discovery ──▶ JD parsing ──▶ matching ──▶ priority
                     │                            │
              ATS feeds, local JDs,          eligibility + technical
              company registry               + domain fit
                                                  │
                          ┌───────────────────────┴──────────────┐
                          ▼                                      ▼
                   resume tailoring                        contact plan
                   (from your evidence)                    (who, and how to find them)
                          └───────────────────┬──────────────────┘
                                              ▼
                              SQLite ─▶ applications.xlsx + dashboard.html
```

## The one rule

**Nothing is claimed on your behalf that your profile cannot back.**

Every skill in the profile can cite evidence - a project, a role, a paper, a
repository. The resume builder can only emit strings that already exist in the
profile, and `verify_resume()` re-checks that afterwards and raises if anything
slipped through. A skill you marked `exploratory`, or one with no evidence at all,
is scored lower and is physically kept off tailored resumes. A guessed email address
is permanently labelled a guess.

That constraint is the whole point. An agent that will happily write "5 years of
TensorFlow" because a JD asked for it is worse than useless.

## Quickstart

```bash
pip install -r requirements.txt          # PyYAML required; requests/openpyxl optional

cp profile.faizan.yaml profile.yaml      # the real profile, built from the CVs
python -m jobpilot audit                 # checks every evidence link resolves

python -m jobpilot demo                  # full pipeline on the bundled sample jobs
open out/demo/dashboard.html
```

Two profiles ship with the repo. `profile.faizan.yaml` is the real one, assembled
from the five CVs - KoshurAI, KoshurOCR, Koshur Diacritizer, the three arXiv
preprints, PromptForge, Groopik, GSSoC and GetInterned, with honest levels
(TensorFlow, Kubernetes, speech and RAG are all marked so they stay off resumes).
`profile.example.yaml` is the blank-slate template if someone else wants to use
this. Keep your working copy in `profile.yaml`, which is git-ignored.

Once your profile is honest, point it at real feeds:

```bash
python -m jobpilot probe --write my_companies.yaml   # find each company's job board
python -m jobpilot run --companies my_companies.yaml
```

## Commands

| Command | What it does |
|---|---|
| `jobpilot audit` | Validates the profile: unknown evidence ids are errors, unbacked "strong" skills are reported |
| `jobpilot run` | The full pass: discover → score → tailor → draft → store → export |
| `jobpilot demo` | Same, offline, on the bundled corpus, using `profile.example.yaml` if you have no profile yet |
| `jobpilot assess <file\|dir>` | Score one JD and print the requirement-by-requirement table (`--resume` also writes the CV) |
| `jobpilot probe --write f.yaml` | Discovers which ATS each company publishes on and records the verified slug |
| `jobpilot companies --domains document_ai` | Browse the company universe |
| `jobpilot status <match> applied` | Move an application along; statuses survive every later run |
| `jobpilot doctor` | Checks dependencies, profile and API reachability |

Useful flags on `run`: `--offline`, `--min-band A`, `--only sarvam_ai`, `--domains
document_ai`, `--no-open-applications`, `--worldwide`, `--llm`.

## Where the jobs come from

**Public ATS APIs** - Greenhouse, Lever, Ashby, Workable and Recruitee all publish a
company's open roles as JSON precisely so aggregators can read them. That is the
primary source: structured, stable, and nobody's terms are being bent. Point the
registry at a company and `probe` works out which board it uses.

**Your own registry** - `jobpilot/data/companies.yaml` seeds ~30 Indian AI
organisations weighted towards Indian-language AI, document AI, speech, foundation
models and research labs. It is a **seed list to verify, not a verified database**:
websites move and founders leave, so confirm before you write to anyone. Add your own
in a second file; yours wins.

**Local job descriptions** - `--jobs some_dir/` reads `.json`, `.md` and `.txt`. This
is how anything the agent cannot fetch gets in: paste the JD you found on LinkedIn,
in a WhatsApp forward or in a PDF into a file with a small front-matter block and it
goes through the identical pipeline.

**What is deliberately not implemented**: scraping LinkedIn/Indeed/Naukri behind
their terms, and buying contact databases. Both would make the tool fragile and get
your accounts banned. The supported path for those sources is: find it manually,
paste it in, let the agent do the analysis.

## How scoring works

Three numbers, because they fail for different reasons and averaging them hides that.

**Eligibility (0-100)** - can you realistically apply? Experience, degree, location,
employment type, work authorisation, salary floor. Some findings are *blockers*
(8+ years, PhD required, a country you cannot work in) and force a `SKIP`. Others are
soft: "2+ years requested vs 0.5" costs points but is exactly the gap a strong
student should still apply through.

**Technical match (0-100)** - weighted over the JD's parsed requirements, required
counting ~3x preferred. Adjacent skills earn partial, capped credit: PyTorch evidence
counts for a TensorFlow requirement at 0.55, never at 1.0.

**Domain fit (0-100)** - does the company work on the problems you have actually
built things in? This is what makes an Indian-language AI lab outrank a
better-paying, worse-fitting SaaS role.

`overall = 0.45·technical + 0.25·domain + 0.30·eligibility`, banded into
**A+ / A / B / C / SKIP**. Speculative entries (no posting) are scored with
domain-heavy weights, discounted, and capped at A - a confirmed opening beats a
letter into the void.

Each one gets a three-line verdict:

```
APPLY - TOP PRIORITY - Computer Vision Engineer - Document AI at Nanonets.
Your strongest ground here: OCR, Computer Vision, PyTorch, Model Evaluation.
Main gap: no material gap in the stated requirements.
Apply through the posting, then follow up with a named person.
```

## Four routes in

| Route | When | Who you write to |
|---|---|---|
| `direct` | There is a posting | Apply, then follow up with a named person |
| `recruiter` | Relevant team, no exact posting | Recruiter or talent lead |
| `founder` | Small/early team | The founder - lead with the work, offer a scoped piece of it |
| `technical` | Research-led org | The ML/research lead, with a technical note rather than a CV blast |

Each route has its own email register, plus a short version, a LinkedIn note under
300 characters, and a follow-up.

## Finding a human, honestly

The agent will not invent a verified contact. For each opportunity it gives you:

- contacts you have already curated in `people.yaml`, ranked for that route;
- the exact public searches to run (`site:linkedin.com/in "Sarvam AI" ("ml lead" OR …)`),
  clickable from the dashboard;
- generic inboxes constructed from the company domain (`careers@…`), labelled as
  guesses;
- `guess_email_candidates()` for name-based patterns - also permanently labelled.

Anything that is not `verified` or `published` shows up as a warning on the draft.

## What you get

`out/applications.xlsx` (or `.csv` without openpyxl) - one row per opportunity:
priority, company, role, the three scores, salary, location, route, contact, contact
email + its status, tailored CV path, email subject, the full email body to copy,
LinkedIn note, why you match, gaps, verdict, job link, status, whether it is new, and
the searches to find a human.

`out/dashboard.html` - the same data as a filterable table; click a row for the whole
application package with copy buttons and a `mailto:` link. Single file, no network,
works offline.

`out/resumes/` - a tailored `.md` and print-ready `.html` per opportunity, with
summary, skills (ranked and trimmed to what the role cares about), experience,
selected projects, publications, education and recognition. Open the HTML and print
to PDF.

`jobpilot.db` - every posting ever seen, so each run reports what is genuinely new,
and your application statuses persist.

## Optional LLM layer

Everything above runs with no API key. With `--llm` (needs `ANTHROPIC_API_KEY` and
`pip install anthropic`) Claude does two narrow jobs: catching requirements phrased in
ways the rules miss, and tightening the wording of a draft. Both are fenced -
extraction is restricted to the existing skill vocabulary, and a polished email is
rejected if it introduced a number, link or address that was not in the original.

## Layout

```
jobpilot/
  profile.py        master profile loading + strict validation
  models.py         every shared type
  parsing/          skill taxonomy, JD → structured requirements
  matching/         eligibility, technical match, domain fit, priority, verdict
  resume/           evidence selection, integrity check, markdown + print HTML
  outreach/         contact plans, search queries, four registers of draft
  discovery/        ATS connectors, company registry, local JD loader
  store/            SQLite: jobs, assessments, people, applications
  export/           xlsx / csv / dashboard
  llm.py            optional, fenced Claude layer
  pipeline.py       the orchestrator
  cli.py            command line
tests/              31 tests, no network, no API key
examples/demo_jobs/ eight sample JDs spanning great fits to obvious skips
```

## Testing

```bash
python -m unittest discover -s tests
```

## Roadmap

Worth adding next, roughly in order of payoff:

1. **Follow-up scheduling** - the database already knows when you first contacted
   someone; surface "8 days, no reply" on the dashboard.
2. **Company-page watching** - many small labs post openings only on their own site;
   a diff-watcher on career pages would catch what no ATS feed carries.
3. **Interview prep packs** - the matcher already knows your gaps for each role.
4. **Outcome feedback** - record which applications got replies and re-weight the
   scoring on what actually works for you.

## Conduct

The agent researches and prepares; you decide and send. Keep it that way: verify a
contact before writing to them, do not send the same paragraph to forty companies,
and do not let any tool put a claim on your CV that you cannot walk into a room and
defend.
