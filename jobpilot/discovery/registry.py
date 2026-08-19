"""The company universe.

Two files feed it:

  * jobpilot/data/companies.yaml - a seed list of Indian AI/ML organisations,
    including research-led startups that are worth approaching whether or not
    they have a posting open. Treat it as a starting point to verify, not as a
    verified database: websites move, ATS slugs change, and founders leave.
    `jobpilot probe` fills in and corrects the ATS details by actually asking
    the endpoints.
  * your own companies.yaml (same shape) - anything you add wins over the seed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from ..models import Company

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "companies.yaml"


def _company_from(raw: dict[str, Any], source: str) -> Company:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("company entry needs a name")
    key = str(raw.get("key") or name.lower().replace(" ", "_").replace(".", "")).strip()
    ats = raw.get("ats") or {}
    return Company(
        key=key,
        name=name,
        website=str(raw.get("website", "")),
        careers_url=str(raw.get("careers_url", "")),
        ats={str(k): str(v) for k, v in ats.items()} if isinstance(ats, dict) else {},
        hq=str(raw.get("hq", "")),
        stage=str(raw.get("stage", "")),
        domains=[str(d).lower().replace(" ", "_").replace("-", "_") for d in raw.get("domains", []) or []],
        about=str(raw.get("about", "")).strip(),
        founders=[{str(k): str(v) for k, v in f.items()} for f in raw.get("founders", []) or []
                  if isinstance(f, dict)],
        signals=[str(s) for s in raw.get("signals", []) or []],
        outreach_modes=[str(m) for m in raw.get("outreach_modes", []) or []],
        source=source,
    )


class Registry:
    def __init__(self, companies: dict[str, Company] | None = None):
        self.companies: dict[str, Company] = dict(companies or {})

    def __len__(self) -> int:
        return len(self.companies)

    def __iter__(self):
        return iter(self.companies.values())

    def get(self, key: str) -> Company | None:
        return self.companies.get(key)

    def add(self, company: Company) -> None:
        existing = self.companies.get(company.key)
        if existing is None:
            self.companies[company.key] = company
            return
        merged = replace(
            existing,
            website=company.website or existing.website,
            careers_url=company.careers_url or existing.careers_url,
            ats=company.ats or existing.ats,
            hq=company.hq or existing.hq,
            stage=company.stage or existing.stage,
            about=company.about or existing.about,
            domains=sorted(set(existing.domains) | set(company.domains)),
            founders=company.founders or existing.founders,
            signals=sorted(set(existing.signals) | set(company.signals)),
            outreach_modes=company.outreach_modes or existing.outreach_modes,
            source=company.source,
        )
        self.companies[company.key] = merged

    def load_file(self, path: str | Path, source: str | None = None) -> int:
        path = Path(path)
        if not path.exists():
            return 0
        if yaml is None:
            raise RuntimeError("PyYAML is required to read company files")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("companies", data if isinstance(data, list) else [])
        count = 0
        for raw in entries or []:
            if isinstance(raw, dict):
                self.add(_company_from(raw, source or str(path)))
                count += 1
        return count

    def select(self, *, domains: Iterable[str] | None = None,
               signals: Iterable[str] | None = None,
               keys: Iterable[str] | None = None,
               with_ats_only: bool = False) -> list[Company]:
        wanted_domains = {d.lower() for d in domains or []}
        wanted_signals = {s.lower() for s in signals or []}
        wanted_keys = {k.lower() for k in keys or []}
        out = []
        for company in self.companies.values():
            if wanted_keys and company.key.lower() not in wanted_keys:
                continue
            if wanted_domains and not wanted_domains & set(company.domains):
                continue
            if wanted_signals and not wanted_signals & {s.lower() for s in company.signals}:
                continue
            if with_ats_only and not company.ats.get("slug"):
                continue
            out.append(company)
        return sorted(out, key=lambda c: c.name.lower())

    def to_yaml(self) -> str:
        if yaml is None:
            raise RuntimeError("PyYAML is required to write company files")
        payload = {"companies": []}
        for company in sorted(self.companies.values(), key=lambda c: c.key):
            entry: dict[str, Any] = {"key": company.key, "name": company.name}
            for field in ("website", "careers_url", "hq", "stage", "about"):
                value = getattr(company, field)
                if value:
                    entry[field] = value
            if company.ats:
                entry["ats"] = company.ats
            for field in ("domains", "signals", "outreach_modes", "founders"):
                value = getattr(company, field)
                if value:
                    entry[field] = value
            payload["companies"].append(entry)
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)


def load_registry(extra: Iterable[str | Path] = (), include_seed: bool = True) -> Registry:
    registry = Registry()
    if include_seed:
        registry.load_file(SEED_PATH, source="seed")
    for path in extra:
        registry.load_file(path, source="user")
    return registry
