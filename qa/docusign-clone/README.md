# DocuSign Clone — QA Take-Home

## Status: blocked on network access

The QA pass itself has **not** been performed. Both applications the assignment
requires are unreachable from this session's sandbox — the egress gateway rejects
them at the CONNECT/request layer, before any authentication happens:

| Host | Result |
|---|---|
| `http://13.207.185.159/` (the clone) | `403` · `x-deny-reason: host_not_allowed` |
| `https://www.docusign.com` (the reference app) | `403` to `CONNECT` — policy denial |
| `https://demo.docusign.net` | `403` to `CONNECT` — policy denial |

The clone's response body is explicit:

```
Host not in allowlist: 13.207.185.159.
Add this host to your network egress settings to allow access.
```

This is **not** an HTTP Basic auth failure. The supplied credentials were never
exercised — the request never left the sandbox.

### To unblock

Add all three hosts to the environment's network egress allowlist, then re-run this
task. See the environment configuration docs:
<https://code.claude.com/docs/en/claude-code-on-the-web>

Both are needed: the clone to test, and DocuSign to diff against. Testing the clone
without the reference would reduce every pixel-fidelity and "expected behavior"
finding to guesswork, which is the opposite of what the assignment asks for.

Note that DocuSign additionally requires a free-trial account. Sign-up needs a real
email and, on some plans, card details — so the trial account should be created by a
human and the session handed credentials, rather than provisioned automatically.

## What is ready

`bug-tracker.xlsx` — the deliverable-1 workbook, built and formula-verified, with
zero findings in it. Three tabs:

- **Bug Tracker** — the 14 required columns in the order the brief specifies
  (Bug ID · Title · Category · Severity · Module / Screen · Steps to Reproduce ·
  Expected Behavior · Actual Behavior · Evidence · Browser + OS · Viewport ·
  Reproducibility · Date Found · Notes / Hypothesis). Dropdowns on Category,
  Severity and Reproducibility; severity colour-codes itself via conditional
  formatting; header row frozen and filterable. Row 2 is a shaded, italic
  **EXAMPLE** row showing the expected level of detail — it is illustrative
  formatting, not a real finding, and the Summary counts exclude it.
- **Summary** — live `COUNTIF` rollups by severity and by category over rows 3–400.
- **Legend & Scope** — per-field filling instructions, the P0–P4 severity
  definitions, and the in-scope / out-of-scope lists from the brief.

Deliverable 2 (the half-page summary note) is intentionally absent. It requires real
findings — overall impression, top 5 bugs, what was skipped — and inventing any of
that would defeat the purpose of the exercise.

## Verification note

`recalc.py` cannot run in this image: LibreOffice 24.2 is installed but its Calc
filter libraries (`libscfiltlo.so`, `libsclo.so`) are missing, so `soffice` fails to
load any spreadsheet with `Error: source file could not be loaded` — reproducible on
a two-cell test file, so it is not specific to this workbook.

The Summary formulas were instead evaluated with the `formulas` Python engine against
a seeded copy (4 known rows across 2 severities and 2 categories). All 12 assertions
passed and no cell evaluated to an error. Because openpyxl writes formulas without
cached values, the count cells will read blank in lightweight previewers until Excel
or Sheets opens the file and recalculates — that happens automatically on open.
