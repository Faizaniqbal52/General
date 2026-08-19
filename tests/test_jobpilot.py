"""Tests for the JobPilot pipeline. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobpilot.discovery.local import load_local_jobs
from jobpilot.discovery.registry import load_registry
from jobpilot.export.rows import package_rows
from jobpilot.export.sheet import write_csv, write_sheet
from jobpilot.matching.engine import assess
from jobpilot.models import Band, Company, Job, Level, Mode, Person, Status
from jobpilot.outreach import build_drafts, contact_plan, guess_email_candidates
from jobpilot.parsing.jd import enrich, extract_min_years, extract_requirements, extract_salary
from jobpilot.parsing.taxonomy import canonical_skill, extract_domains, extract_skills
from jobpilot.pipeline import Config, run as run_pipeline
from jobpilot.profile import ProfileError, load_profile
from jobpilot.resume import build_resume, render_html, render_markdown, verify_resume
from jobpilot.resume.tailor import ResumeIntegrityError
from jobpilot.store import Store

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile.example.yaml"
DEMO = ROOT / "examples" / "demo_jobs"


def sample_job(**kwargs) -> Job:
    defaults = dict(id="j1", company_key="acme", company_name="Acme AI",
                    title="NLP Engineer", location="Bengaluru",
                    description="Requirements\n- Python and PyTorch\n- NLP and LLMs\n")
    defaults.update(kwargs)
    return enrich(Job(**defaults))


class TaxonomyTests(unittest.TestCase):
    def test_alias_resolution(self):
        self.assertEqual(canonical_skill("Hugging Face"), "huggingface")
        self.assertEqual(canonical_skill("torch"), "pytorch")
        self.assertIsNone(canonical_skill("underwater basket weaving"))

    def test_plurals_but_not_short_words(self):
        self.assertIn("foundation_models", extract_domains("we train foundational models"))
        self.assertNotIn("c", extract_skills("B.Tech in CS or equivalent"))
        self.assertIn("cpp", extract_skills("strong C++ background"))


class ParsingTests(unittest.TestCase):
    def test_required_vs_preferred(self):
        text = ("Requirements\n- Python\n- PyTorch\n"
                "Nice to have\n- Kubernetes\n- Familiarity with AWS\n")
        by_skill = {r.skill: r.necessity.value for r in extract_requirements(text)}
        self.assertEqual(by_skill["python"], "required")
        self.assertEqual(by_skill["kubernetes"], "preferred")
        self.assertEqual(by_skill["aws"], "preferred")

    def test_years_and_salary(self):
        self.assertEqual(extract_min_years("3+ years of experience"), 3.0)
        self.assertEqual(extract_min_years("Freshers welcome"), 0.0)
        self.assertIsNone(extract_min_years("after 3 years of college"))
        raw, lo, hi = extract_salary("Compensation: ₹18-32 LPA")
        self.assertEqual((lo, hi), (18.0, 32.0))
        self.assertTrue(raw)

    def test_employment_type_and_remote(self):
        job = sample_job(title="ML Intern", description="Remote internship for students")
        self.assertEqual(job.employment_type, "internship")
        self.assertTrue(job.remote)
        hybrid = sample_job(description="Hybrid, remote two days a week")
        self.assertFalse(hybrid.remote)


class ProfileTests(unittest.TestCase):
    def test_example_profile_loads(self):
        profile = load_profile(PROFILE)
        self.assertTrue(profile.skills["pytorch"].is_evidenced)
        self.assertEqual(profile.level_of("tensorflow"), Level.EXPLORATORY)

    def test_unknown_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "p.yaml"
            bad.write_text("identity:\n  name: X\nskills:\n  - {name: python, level: strong, "
                           "evidence: [nope]}\n", encoding="utf-8")
            with self.assertRaises(ProfileError):
                load_profile(bad)

    def test_unevidenced_skill_is_discounted(self):
        profile = load_profile(PROFILE)
        self.assertLess(profile.skills["sql"].credibility, Level.BASIC.weight)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)

    def test_strong_match_is_prioritised(self):
        job = sample_job(description=("Requirements\n- Python, PyTorch\n- NLP and LLMs\n"
                                      "- OCR and computer vision\n"))
        result = assess(self.profile, job)
        self.assertGreater(result.technical_match, 80)
        self.assertIn(result.band, {Band.A_PLUS, Band.A})
        self.assertTrue(result.should_apply)

    def test_blockers_force_skip(self):
        job = sample_job(title="Principal ML Engineer", location="Singapore",
                         description="Requirements\n- 9+ years of experience\n- PhD required\n")
        result = assess(self.profile, job)
        self.assertEqual(result.band, Band.SKIP)
        self.assertTrue(result.blockers)
        self.assertTrue(result.verdict.startswith("SKIP"))

    def test_adjacent_skill_gets_partial_credit(self):
        job = sample_job(description="Requirements\n- TensorFlow\n")
        matches = {m.requirement.skill: m for m in assess(self.profile, job).matches}
        # PyTorch evidence carries some TensorFlow credit, but never full credit
        self.assertGreater(matches["tensorflow"].score, 0.3)
        self.assertLessEqual(matches["tensorflow"].score, 0.6)

    def test_experience_gap_is_soft_not_fatal(self):
        job = sample_job(description="Requirements\n- 2+ years experience\n- Python, PyTorch, NLP\n")
        result = assess(self.profile, job)
        self.assertFalse(result.blockers)
        self.assertLess(result.eligibility, 100)
        self.assertTrue(any("2+ years" in g for g in result.gaps))

    def test_speculative_never_outranks_a_real_posting_band(self):
        company = Company(key="c", name="C", domains=["indian_language_ai", "low_resource_nlp"],
                          about="Indian-language AI", outreach_modes=["founder"])
        job = sample_job(description="Indian-language AI", source="open_application")
        result = assess(self.profile, job, company, has_posting=False)
        self.assertNotEqual(result.band, Band.A_PLUS)
        self.assertEqual(result.mode, Mode.FOUNDER)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)
        self.job = sample_job(description="Requirements\n- OCR, computer vision, PyTorch\n")
        self.assessment = assess(self.profile, self.job)

    def test_only_evidenced_skills_are_featured(self):
        resume = build_resume(self.profile, self.job, self.assessment)
        featured = {label for _, labels in resume.skill_groups for label in labels}
        self.assertIn("PyTorch", featured)
        self.assertNotIn("TensorFlow", featured)   # exploratory
        self.assertNotIn("SQL", featured)          # no evidence
        verify_resume(resume, self.profile)

    def test_tailoring_reorders_for_the_job(self):
        ocr_resume = build_resume(self.profile, self.job, self.assessment)
        llm_job = sample_job(id="j2", description="Requirements\n- LLMs, fine-tuning, evaluation\n")
        llm_resume = build_resume(self.profile, llm_job, assess(self.profile, llm_job))
        self.assertEqual(ocr_resume.projects[0].evidence_id, "koshur_ocr")
        self.assertEqual(llm_resume.projects[0].evidence_id, "koshur_ai")

    def test_verification_catches_fabrication(self):
        resume = build_resume(self.profile, self.job, self.assessment)
        resume.skill_groups.append(("Invented", ["Kubernetes at scale"]))
        with self.assertRaises(ResumeIntegrityError):
            verify_resume(resume, self.profile)

    def test_verification_catches_invented_highlight(self):
        resume = build_resume(self.profile, self.job, self.assessment)
        resume.projects[0].highlights.append("Led a team of 20 engineers")
        with self.assertRaises(ResumeIntegrityError):
            verify_resume(resume, self.profile)

    def test_renderers_produce_output(self):
        resume = build_resume(self.profile, self.job, self.assessment)
        self.assertIn(self.profile.name, render_markdown(resume))
        html = render_html(resume)
        self.assertIn("<!doctype html>", html)
        self.assertIn("KoshurOCR", html)


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)
        self.company = Company(key="acme", name="Acme AI", website="https://acme.ai",
                               about="Builds document AI for Indian languages.",
                               domains=["document_ai"])
        self.job = sample_job(description="Requirements\n- OCR, PyTorch\n")
        self.assessment = assess(self.profile, self.job, self.company)

    def test_draft_mentions_company_and_evidence(self):
        draft = build_drafts(self.profile, self.job, self.assessment, self.company)
        self.assertIn("Acme AI", draft.subject + draft.body)
        self.assertIn("Koshur", draft.body)
        self.assertLessEqual(len(draft.linkedin_note), 300)
        self.assertTrue(draft.warnings)          # no contact known yet

    def test_guessed_email_is_flagged_not_trusted(self):
        person = Person(key="p", company_key="acme", name="A Person",
                        email="a@acme.ai", email_status="pattern_guess", email_confidence=0.25)
        draft = build_drafts(self.profile, self.job, self.assessment, self.company, person)
        self.assertFalse(person.is_safe_to_email)
        self.assertTrue(any("pattern guess" in w for w in draft.warnings))

    def test_email_candidates_and_plan(self):
        candidates = guess_email_candidates("Asha Menon", self.company)
        self.assertIn("asha.menon@acme.ai", candidates)
        plan = contact_plan(self.company, self.job, self.assessment.mode)
        self.assertTrue(plan["searches"])
        self.assertTrue(any(p.email.startswith("careers@") for p in plan["generic_inboxes"]))


class LLMTests(unittest.TestCase):
    """The optional LLM layer must never be able to add a claim."""

    class FakeBlock:
        def __init__(self, text): self.type, self.text = "text", text

    class FakeResponse:
        def __init__(self, text): self.content = [LLMTests.FakeBlock(text)]

    class FakeClient:
        def __init__(self, reply): self.reply, self.messages = reply, self
        def create(self, **kwargs): return LLMTests.FakeResponse(self.reply)

    def test_null_enricher_is_the_default(self):
        from jobpilot.llm import NullEnricher, from_env
        self.assertIsInstance(from_env(enabled=False), NullEnricher)

    def test_only_vocabulary_keys_survive(self):
        from jobpilot.llm import ClaudeEnricher
        reply = ('{"requirements": [{"skill": "mlops", "necessity": "preferred", "evidence": "x"},'
                 ' {"skill": "telepathy", "necessity": "required", "evidence": "y"}]}')
        enricher = ClaudeEnricher(client=self.FakeClient(reply))
        job = sample_job()
        merged = {r.skill for r in enricher.extend_requirements(job)}
        self.assertIn("mlops", merged)
        self.assertNotIn("telepathy", merged)

    def test_polish_rejects_invented_facts(self):
        from jobpilot.llm import ClaudeEnricher
        original = "I built KoshurOCR in PyTorch."
        added = "I built KoshurOCR in PyTorch and led 12 engineers at BigCo."
        self.assertEqual(ClaudeEnricher(client=self.FakeClient(added)).polish_email(original),
                         original)
        clean = "I built KoshurOCR with PyTorch."
        self.assertEqual(ClaudeEnricher(client=self.FakeClient(clean)).polish_email(original),
                         clean)

    def test_broken_response_falls_back_to_rules(self):
        from jobpilot.llm import ClaudeEnricher
        job = sample_job()
        enricher = ClaudeEnricher(client=self.FakeClient("not json at all"))
        self.assertEqual(len(enricher.extend_requirements(job)), len(job.requirements))


class StoreTests(unittest.TestCase):
    def test_round_trip_and_new_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp) / "db.sqlite") as store:
                job = sample_job()
                self.assertTrue(store.upsert_job(job))
                self.assertFalse(store.upsert_job(job))
                profile = load_profile(PROFILE)
                result = assess(profile, job)
                store.upsert_assessment(result)
                back = store.get_assessment(job.id)
                self.assertEqual(back.overall, result.overall)
                self.assertEqual(back.band, result.band)
                self.assertEqual(len(back.matches), len(result.matches))
                store.set_status(job.id, Status.APPLIED, "note")
                self.assertEqual(store.get_application(job.id).status, Status.APPLIED)

    def test_status_survives_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db.sqlite"
            with Store(db) as store:
                job = sample_job()
                store.upsert_job(job)
                store.set_status(job.id, Status.INTERVIEW)
            with Store(db) as store:
                from jobpilot.models import Application
                store.upsert_application(Application(job_id=job.id, email_subject="new draft"))
                self.assertEqual(store.get_application(job.id).status, Status.INTERVIEW)


class DiscoveryTests(unittest.TestCase):
    def test_demo_corpus_parses(self):
        jobs = load_local_jobs(DEMO)
        self.assertGreaterEqual(len(jobs), 8)
        titles = {job.title for job in jobs}
        self.assertIn("Computer Vision Engineer - Document AI", titles)
        sarvam = next(j for j in jobs if j.company_key == "sarvam_ai")
        self.assertIn("foundational models", sarvam.description)

    def test_seed_registry_is_usable(self):
        registry = load_registry()
        self.assertGreater(len(registry), 20)
        self.assertTrue(registry.select(domains=["document_ai"]))
        self.assertTrue(registry.get("sarvam_ai"))


class PipelineTests(unittest.TestCase):
    def test_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(profile_path=str(PROFILE), db_path=str(Path(tmp) / "db.sqlite"),
                            out_dir=str(Path(tmp) / "out"), local_jobs=[str(DEMO)],
                            offline=True, people_file=str(Path(tmp) / "none.yaml"))
            report = run_pipeline(config)
            self.assertGreater(len(report.packages), 5)
            self.assertEqual(report.new_jobs, report.fetched - report.filtered_out)
            top = report.packages[0]
            self.assertTrue(Path(top.resume_html_path).exists())
            self.assertTrue(top.draft.body)

            rows = package_rows(report.packages)
            self.assertEqual(rows[0]["priority"], top.assessment.band.value)
            csv_path = write_csv(rows, Path(tmp) / "out" / "apps.csv")
            self.assertTrue(csv_path.exists())
            sheet = write_sheet(rows, Path(tmp) / "out" / "apps.xlsx")
            self.assertTrue(sheet.exists())

            from jobpilot.export import write_dashboard
            dashboard = write_dashboard(report.packages, Path(tmp) / "out" / "d.html")
            text = dashboard.read_text(encoding="utf-8")
            self.assertIn("JobPilot", text)
            self.assertIn(top.job.company_name, text)

            # a second run finds nothing new and keeps statuses
            second = run_pipeline(config)
            self.assertEqual(second.new_jobs, 0)

    def test_skip_band_is_not_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(profile_path=str(PROFILE), db_path=str(Path(tmp) / "db.sqlite"),
                            out_dir=str(Path(tmp) / "out"), local_jobs=[str(DEMO)],
                            offline=True, include_open_applications=False,
                            people_file=str(Path(tmp) / "none.yaml"))
            report = run_pipeline(config)
            packaged = {p.job.company_key for p in report.packages}
            self.assertNotIn("globalscale", packaged)


if __name__ == "__main__":
    unittest.main()
