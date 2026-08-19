"""JobPilot - a personal, evidence-backed AI job-hunting agent.

The pipeline is: profile -> discovery -> parsing -> matching -> priority ->
resume tailoring -> outreach drafting -> application database -> dashboard.

Design rules that the whole package is built around:

1. Nothing is claimed on your behalf that is not backed by evidence in your
   master profile. The resume tailorer physically cannot emit a skill or a
   project that is not in the profile.
2. Discovery only uses public, machine-readable job feeds (ATS APIs, career
   pages, RSS) and whatever search backend you plug in. No credentialed
   scraping of sites that forbid it.
3. Contact details are stored with a source and a confidence. A guessed email
   is always labelled as a guess and never treated as verified.
4. The agent never sends anything. It prepares; you review and send.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
