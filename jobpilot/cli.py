"""Command line interface.

    python -m jobpilot demo                  # full pipeline on the bundled corpus
    python -m jobpilot audit                 # check the master profile
    python -m jobpilot run                   # the real thing
    python -m jobpilot probe --write my.yaml # find which ATS each company uses
    python -m jobpilot assess path/to/jd.md  # score one job description
    python -m jobpilot status sarvam applied # move an application along
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .discovery import load_registry, probe_ats
from .discovery.local import load_local_jobs
from .export import package_rows, write_dashboard, write_sheet
from .matching.engine import assess as assess_job
from .models import Band, Company, Status
from .net import Client
from .parsing.jd import enrich
from .pipeline import Config, Package, RunReport, run as run_pipeline
from .profile import ProfileError, audit as audit_profile, load_profile
from .resume import build_resume, render_html, render_markdown, verify_resume
from .store import Store

DEMO_DIR = Path(__file__).resolve().parent.parent / "examples" / "demo_jobs"
EXAMPLE_PROFILE = Path(__file__).resolve().parent.parent / "profile.example.yaml"

BAND_NAMES = {"A+": Band.A_PLUS, "A": Band.A, "B": Band.B, "C": Band.C, "SKIP": Band.SKIP}


def _print_report(report: RunReport, config: Config) -> None:
    counts = report.by_band()
    print(f"\nfetched {report.fetched} postings · "
          f"{report.filtered_out} filtered out · {report.new_jobs} new since last run")
    if counts:
        print("packages: " + " · ".join(f"{band} {counts[band]}" for band in
                                        sorted(counts, key=lambda b: list(BAND_NAMES).index(b))))
    for note in report.notes:
        print(f"  note: {note}")
    for error in report.errors[:10]:
        print(f"  ! {error}")
    if len(report.errors) > 10:
        print(f"  ! ... and {len(report.errors) - 10} more")

    print()
    for package in report.packages[:20]:
        assessment = package.assessment
        flag = " NEW" if package.is_new else ""
        print(f"[{assessment.band.value:>4}] {assessment.overall:5.1f}  "
              f"{package.job.company_name[:26]:<26} {package.job.title[:44]:<44}"
              f" {assessment.mode.value}{flag}")
    if len(report.packages) > 20:
        print(f"       ... and {len(report.packages) - 20} more in the sheet")


def _export(report: RunReport, config: Config) -> tuple[Path, Path]:
    out = Path(config.out_dir)
    rows = package_rows(report.packages)
    sheet = write_sheet(rows, out / "applications.xlsx")
    dashboard = write_dashboard(report.packages, out / "dashboard.html")
    return sheet, dashboard


def cmd_audit(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    notes = audit_profile(profile)
    evidenced = sum(1 for s in profile.skills.values() if s.is_evidenced)
    print(f"{profile.name}: {len(profile.skills)} skills ({evidenced} evidence-backed), "
          f"{len(profile.evidence)} evidence items, domains: "
          f"{', '.join(sorted(profile.domains())) or 'none'}")
    if not notes:
        print("profile looks consistent.")
        return 0
    print("\nthings to fix:")
    for note in notes:
        print(f"  - {note}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = Config(
        profile_path=args.profile,
        db_path=args.db,
        out_dir=args.out,
        company_files=args.companies or [],
        people_file=args.people,
        local_jobs=args.jobs or [],
        offline=args.offline,
        india_only=not args.worldwide,
        role_filter=not args.all_roles,
        include_open_applications=not args.no_open_applications,
        min_band=BAND_NAMES.get(args.min_band, Band.C),
        company_keys=args.only or [],
        company_domains=args.domains or [],
        use_llm=getattr(args, "llm", False),
    )
    report = run_pipeline(config)
    _print_report(report, config)
    sheet, dashboard = _export(report, config)
    print(f"\nsheet:     {sheet}")
    print(f"dashboard: {dashboard}")
    print(f"resumes:   {Path(config.out_dir) / 'resumes'}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    profile = args.profile
    if not Path(profile).exists():
        profile = str(EXAMPLE_PROFILE)
        print(f"(no {args.profile} yet - running on {EXAMPLE_PROFILE.name})")
    args = argparse.Namespace(**{**vars(args), "profile": profile, "offline": True,
                                 "jobs": [str(DEMO_DIR)], "db": args.db, "out": args.out,
                                 "companies": [], "people": args.people, "worldwide": False,
                                 "all_roles": False, "no_open_applications": False,
                                 "min_band": args.min_band, "only": [], "domains": [],
                                 "llm": getattr(args, "llm", False)})
    return cmd_run(args)


def cmd_probe(args: argparse.Namespace) -> int:
    registry = load_registry(args.companies or [])
    client = Client(cache_dir=args.cache)
    found = 0
    for company in registry.select(keys=args.only or None):
        if company.ats.get("slug") and not args.force:
            continue
        result = probe_ats(client, company)
        if result:
            provider, slug = result
            company.ats = {"provider": provider, "slug": slug}
            found += 1
            print(f"  {company.name}: {provider}/{slug}")
        else:
            print(f"  {company.name}: no public board found "
                  f"(check {company.careers_url or company.website or 'the site'} by hand)")
    if args.write:
        Path(args.write).write_text(registry.to_yaml(), encoding="utf-8")
        print(f"\nwrote {found} discovered boards into {args.write}")
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    registry = load_registry(args.companies or [])
    jobs = load_local_jobs(args.path)
    if not jobs:
        print(f"no job description found at {args.path}")
        return 1
    for job in jobs:
        enrich(job)
        company = registry.get(job.company_key)
        assessment = assess_job(profile, job, company)
        print("=" * 72)
        print(f"{job.title} @ {job.company_name} ({job.location or 'location unknown'})")
        print(f"eligibility {assessment.eligibility} · technical {assessment.technical_match} · "
              f"domain {assessment.domain_fit} · overall {assessment.overall} "
              f"[{assessment.band.value}]")
        print()
        print(assessment.verdict)
        print("\nrequirement by requirement:")
        for match in sorted(assessment.matches, key=lambda m: -m.score):
            mark = "ok " if match.score >= 0.7 else "~  " if match.score >= 0.4 else "GAP"
            print(f"  {mark} {match.requirement.label:<26} "
                  f"{match.requirement.necessity.value:<9} {match.score * 100:5.0f}%"
                  + (f"  ({', '.join(match.evidence_ids[:2])})" if match.evidence_ids else ""))
        if args.resume:
            resume = build_resume(profile, job, assessment)
            verify_resume(resume, profile)
            out = Path(args.out) / "resumes"
            out.mkdir(parents=True, exist_ok=True)
            stem = f"{job.company_key}_{job.id[:6]}"
            (out / f"{stem}.md").write_text(render_markdown(resume, include_notes=True), encoding="utf-8")
            (out / f"{stem}.html").write_text(render_html(resume), encoding="utf-8")
            print(f"\nresume: {out / (stem + '.html')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        status = Status(args.status)
    except ValueError:
        print(f"unknown status '{args.status}'. options: "
              + ", ".join(s.value for s in Status))
        return 1
    with Store(args.db) as store:
        matches = [job for job in store.jobs()
                   if args.match.lower() in (job.company_name + " " + job.title + " " + job.id).lower()]
        if not matches:
            print(f"nothing matches '{args.match}'")
            return 1
        if len(matches) > 1 and not args.all:
            print(f"'{args.match}' matches {len(matches)} entries:")
            for job in matches[:15]:
                print(f"  {job.id}  {job.company_name} - {job.title}")
            print("re-run with a more specific string, the job id, or --all")
            return 1
        for job in matches:
            store.set_status(job.id, status, args.note)
            print(f"{job.company_name} - {job.title}: {status.value}")
    return 0


def cmd_companies(args: argparse.Namespace) -> int:
    registry = load_registry(args.companies or [])
    selected = registry.select(domains=args.domains or None, signals=args.signals or None)
    for company in selected:
        board = f"{company.ats.get('provider')}/{company.ats.get('slug')}" if company.ats.get("slug") else "-"
        print(f"{company.key:<24} {company.name:<32} {company.hq[:18]:<18} "
              f"{','.join(company.domains[:3]):<44} {board}")
    print(f"\n{len(selected)} of {len(registry)} companies")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"jobpilot {__version__} · python {sys.version.split()[0]}")
    for module in ("yaml", "requests", "openpyxl"):
        try:
            __import__(module)
            print(f"  [ok]   {module}")
        except ModuleNotFoundError:
            need = {"yaml": "required for profile/company files",
                    "requests": "optional, urllib is used otherwise",
                    "openpyxl": "optional, CSV export is used otherwise"}[module]
            print(f"  [miss] {module} - {need}")
    profile_path = Path(args.profile)
    print(f"  [{'ok' if profile_path.exists() else 'miss'}]   profile at {profile_path}")
    if not args.offline:
        client = Client(cache_dir=args.cache)
        for name, url in (("greenhouse", "https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs"),
                          ("lever", "https://api.lever.co/v0/postings/leverdemo?mode=json")):
            try:
                client.get(url, max_age=0)
                print(f"  [ok]   {name} API reachable")
            except Exception as exc:  # noqa: BLE001 - doctor reports whatever went wrong
                print(f"  [warn] {name} unreachable: {str(exc)[:90]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobpilot",
                                     description="Personal, evidence-backed job-hunting agent.")
    parser.add_argument("--version", action="version", version=f"jobpilot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", default="profile.yaml")
        p.add_argument("--db", default="jobpilot.db")
        p.add_argument("--out", default="out")
        p.add_argument("--companies", action="append", help="extra companies.yaml (repeatable)")
        p.add_argument("--people", default="people.yaml")

    p_audit = sub.add_parser("audit", help="validate the master profile")
    p_audit.add_argument("--profile", default="profile.yaml")
    p_audit.set_defaults(func=cmd_audit)

    p_run = sub.add_parser("run", help="discover, score, tailor, draft and export")
    common(p_run)
    p_run.add_argument("--jobs", action="append", help="local job files/dirs (repeatable)")
    p_run.add_argument("--offline", action="store_true", help="use cache and local files only")
    p_run.add_argument("--worldwide", action="store_true", help="do not restrict to India")
    p_run.add_argument("--all-roles", action="store_true", help="skip the role-title filter")
    p_run.add_argument("--no-open-applications", action="store_true",
                       help="only score real postings")
    p_run.add_argument("--min-band", default="C", choices=list(BAND_NAMES))
    p_run.add_argument("--llm", action="store_true",
                       help="use Claude to catch requirements the rules miss and tighten "
                            "the drafts (needs ANTHROPIC_API_KEY and the anthropic package)")
    p_run.add_argument("--only", action="append", help="restrict to these company keys")
    p_run.add_argument("--domains", action="append", help="restrict to these company domains")
    p_run.set_defaults(func=cmd_run)

    p_demo = sub.add_parser("demo", help="run the whole pipeline on the bundled sample jobs")
    common(p_demo)
    p_demo.add_argument("--min-band", default="C", choices=list(BAND_NAMES))
    p_demo.set_defaults(func=cmd_demo, out="out/demo", db="out/demo/jobpilot.db")

    p_probe = sub.add_parser("probe", help="discover which ATS each company publishes on")
    p_probe.add_argument("--companies", action="append")
    p_probe.add_argument("--only", action="append")
    p_probe.add_argument("--write", help="write the merged registry here")
    p_probe.add_argument("--force", action="store_true", help="re-probe even if a slug is known")
    p_probe.add_argument("--cache", default=".jobpilot-cache")
    p_probe.set_defaults(func=cmd_probe)

    p_assess = sub.add_parser("assess", help="score one job description file or directory")
    p_assess.add_argument("path")
    p_assess.add_argument("--profile", default="profile.yaml")
    p_assess.add_argument("--companies", action="append")
    p_assess.add_argument("--resume", action="store_true", help="also write a tailored resume")
    p_assess.add_argument("--out", default="out")
    p_assess.set_defaults(func=cmd_assess)

    p_status = sub.add_parser("status", help="update an application's status")
    p_status.add_argument("match", help="company name, role or job id")
    p_status.add_argument("status", choices=[s.value for s in Status])
    p_status.add_argument("--note", default="")
    p_status.add_argument("--db", default="jobpilot.db")
    p_status.add_argument("--all", action="store_true", help="apply to every match")
    p_status.set_defaults(func=cmd_status)

    p_companies = sub.add_parser("companies", help="list the company universe")
    p_companies.add_argument("--companies", action="append")
    p_companies.add_argument("--domains", action="append")
    p_companies.add_argument("--signals", action="append")
    p_companies.set_defaults(func=cmd_companies)

    p_doctor = sub.add_parser("doctor", help="check the environment")
    p_doctor.add_argument("--profile", default="profile.yaml")
    p_doctor.add_argument("--offline", action="store_true")
    p_doctor.add_argument("--cache", default=".jobpilot-cache")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"missing file: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
