"""SQLite application database.

One file holds the whole pipeline state: which companies are being watched,
which postings have been seen (so tomorrow's run can tell you what is new),
what each one scored, which resume was generated, which human you found, what
was drafted, and where the application stands.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import (Application, Assessment, Band, Company, Job, Mode, Person,
                      Status, to_jsonable)

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    key TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, company_key TEXT NOT NULL, title TEXT NOT NULL, url TEXT,
    source TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assessments (
    job_id TEXT PRIMARY KEY, overall REAL, band TEXT, mode TEXT, data TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS people (
    key TEXT PRIMARY KEY, company_key TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_key);
CREATE INDEX IF NOT EXISTS people_company ON people(company_key);
CREATE INDEX IF NOT EXISTS assessments_band ON assessments(band);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), ensure_ascii=False)


class Store:
    def __init__(self, path: str | Path = "jobpilot.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.commit()
        self.close()

    # -- companies -------------------------------------------------------
    def upsert_company(self, company: Company) -> None:
        self.conn.execute(
            "INSERT INTO companies(key, name, data, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET name=excluded.name, data=excluded.data, "
            "updated_at=excluded.updated_at",
            (company.key, company.name, _dump(company), _now()))

    def get_company(self, key: str) -> Company | None:
        row = self.conn.execute("SELECT data FROM companies WHERE key=?", (key,)).fetchone()
        return Company(**json.loads(row["data"])) if row else None

    def companies(self) -> list[Company]:
        rows = self.conn.execute("SELECT data FROM companies ORDER BY name").fetchall()
        return [Company(**json.loads(r["data"])) for r in rows]

    # -- jobs ------------------------------------------------------------
    def job_exists(self, job_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is not None

    def upsert_job(self, job: Job) -> bool:
        """Returns True when this posting had never been seen before."""
        now = _now()
        is_new = not self.job_exists(job.id)
        if is_new:
            self.conn.execute(
                "INSERT INTO jobs(id, company_key, title, url, source, first_seen, last_seen, data) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (job.id, job.company_key, job.title, job.url, job.source, now, now, _dump(job)))
        else:
            self.conn.execute("UPDATE jobs SET last_seen=?, data=?, title=?, url=? WHERE id=?",
                              (now, _dump(job), job.title, job.url, job.id))
        return is_new

    def get_job(self, job_id: str) -> Job | None:
        row = self.conn.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job_from_json(row["data"]) if row else None

    def jobs(self, company_key: str | None = None) -> list[Job]:
        if company_key:
            rows = self.conn.execute("SELECT data FROM jobs WHERE company_key=?", (company_key,)).fetchall()
        else:
            rows = self.conn.execute("SELECT data FROM jobs").fetchall()
        return [_job_from_json(r["data"]) for r in rows]

    def first_seen(self, job_id: str) -> str:
        row = self.conn.execute("SELECT first_seen FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["first_seen"] if row else ""

    # -- assessments -----------------------------------------------------
    def upsert_assessment(self, assessment: Assessment) -> None:
        self.conn.execute(
            "INSERT INTO assessments(job_id, overall, band, mode, data, updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET overall=excluded.overall, band=excluded.band, "
            "mode=excluded.mode, data=excluded.data, updated_at=excluded.updated_at",
            (assessment.job_id, assessment.overall, assessment.band.value, assessment.mode.value,
             _dump(assessment), _now()))

    def get_assessment(self, job_id: str) -> Assessment | None:
        row = self.conn.execute("SELECT data FROM assessments WHERE job_id=?", (job_id,)).fetchone()
        return _assessment_from_json(row["data"]) if row else None

    def assessments(self, bands: Iterable[str] | None = None) -> list[Assessment]:
        if bands:
            marks = ",".join("?" * len(list(bands)))
            rows = self.conn.execute(
                f"SELECT data FROM assessments WHERE band IN ({marks}) ORDER BY overall DESC",
                tuple(bands)).fetchall()
        else:
            rows = self.conn.execute("SELECT data FROM assessments ORDER BY overall DESC").fetchall()
        return [_assessment_from_json(r["data"]) for r in rows]

    # -- people ----------------------------------------------------------
    def upsert_person(self, person: Person) -> None:
        self.conn.execute(
            "INSERT INTO people(key, company_key, data, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET company_key=excluded.company_key, data=excluded.data, "
            "updated_at=excluded.updated_at",
            (person.key, person.company_key, _dump(person), _now()))

    def people(self, company_key: str | None = None) -> list[Person]:
        if company_key:
            rows = self.conn.execute("SELECT data FROM people WHERE company_key=?", (company_key,)).fetchall()
        else:
            rows = self.conn.execute("SELECT data FROM people").fetchall()
        return [Person(**json.loads(r["data"])) for r in rows]

    def get_person(self, key: str) -> Person | None:
        row = self.conn.execute("SELECT data FROM people WHERE key=?", (key,)).fetchone()
        return Person(**json.loads(row["data"])) if row else None

    # -- applications ----------------------------------------------------
    def upsert_application(self, application: Application, *, preserve_status: bool = True) -> None:
        existing = self.get_application(application.job_id)
        if existing and preserve_status:
            application.status = existing.status
            application.notes = application.notes or existing.notes
        application.updated_at = _now()[:10]
        self.conn.execute(
            "INSERT INTO applications(job_id, status, data, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, data=excluded.data, "
            "updated_at=excluded.updated_at",
            (application.job_id, application.status.value, _dump(application), _now()))

    def get_application(self, job_id: str) -> Application | None:
        row = self.conn.execute("SELECT data FROM applications WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        blob = json.loads(row["data"])
        blob["status"] = Status(blob.get("status", "not_contacted"))
        return Application(**blob)

    def set_status(self, job_id: str, status: Status, note: str = "") -> bool:
        application = self.get_application(job_id) or Application(job_id=job_id)
        application.status = status
        if note:
            application.notes = (application.notes + "\n" if application.notes else "") + note
        self.upsert_application(application, preserve_status=False)
        return True

    def applications(self) -> list[Application]:
        rows = self.conn.execute("SELECT job_id FROM applications").fetchall()
        return [app for app in (self.get_application(r["job_id"]) for r in rows) if app]

    def commit(self) -> None:
        self.conn.commit()

    # -- reporting -------------------------------------------------------
    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("companies", "jobs", "assessments", "people", "applications"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        return out


def _job_from_json(blob: str) -> Job:
    from ..models import Necessity, Requirement
    data = json.loads(blob)
    data["requirements"] = [
        Requirement(skill=r["skill"], label=r["label"],
                    necessity=Necessity(r.get("necessity", "required")), raw=r.get("raw", ""))
        for r in data.get("requirements", [])]
    return Job(**data)


def _assessment_from_json(blob: str) -> Assessment:
    from ..models import Level, Necessity, Requirement, RequirementMatch
    data = json.loads(blob)
    data["band"] = Band(data.get("band", "SKIP"))
    data["mode"] = Mode(data.get("mode", "direct"))
    data["matches"] = [
        RequirementMatch(
            requirement=Requirement(skill=m["requirement"]["skill"], label=m["requirement"]["label"],
                                    necessity=Necessity(m["requirement"].get("necessity", "required")),
                                    raw=m["requirement"].get("raw", "")),
            your_level=Level(m.get("your_level", "none")),
            score=float(m.get("score", 0.0)),
            evidence_ids=m.get("evidence_ids", []))
        for m in data.get("matches", [])]
    return Assessment(**data)
