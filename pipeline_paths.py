"""
pipeline_paths.py
──────────────────
Single source of truth for all pipeline directory paths.
Import this in every pipeline file instead of defining paths locally.

Usage:
    from src.pipeline_paths import PATHS
    PATHS.parsed.mkdir(parents=True, exist_ok=True)
"""

from pathlib import Path
from dataclasses import dataclass


# ── Root output folder ────────────────────────────────────────────────────────
# Everything the pipeline produces lives under this one folder.
# Change this one line to move the entire pipeline output.
PIPELINE_ROOT = Path("pipeline_outputs")


@dataclass(frozen=True)
class PipelinePaths:
    # Step 1 — Parse
    parsed:           Path   # raw parsed .txt files
    parsed_metadata:  Path   # parser metadata JSON per file

    # Step 2 — Analyse
    cleaned:          Path   # cleaned .txt files (for inspection)
    extractions:      Path   # one _extraction.json per indent

    # Step 3 — Frequency
    frequency:        Path   # practice_frequency_report.json + examples

    # Step 4 — Standard
    standard:         Path   # best_practice_standard.json

    # Logs
    logs:             Path   # error logs

    # Convenience: specific output files
    @property
    def frequency_report(self) -> Path:
        return self.frequency / "practice_frequency_report.json"

    @property
    def representative_examples(self) -> Path:
        return self.frequency / "representative_examples.json"

    @property
    def best_practice_standard(self) -> Path:
        return self.standard / "best_practice_standard.json"

    def ensure_all(self):
        """Create all directories."""
        for p in [
            self.parsed, self.parsed_metadata,
            self.cleaned, self.extractions,
            self.frequency, self.standard, self.logs,
        ]:
            p.mkdir(parents=True, exist_ok=True)


PATHS = PipelinePaths(
    parsed          = PIPELINE_ROOT / "01_parsed",
    parsed_metadata = PIPELINE_ROOT / "01_parsed_metadata",
    cleaned         = PIPELINE_ROOT / "02_cleaned",
    extractions     = PIPELINE_ROOT / "03_extractions",
    frequency       = PIPELINE_ROOT / "04_frequency",
    standard        = PIPELINE_ROOT / "05_standard",
    logs            = PIPELINE_ROOT / "logs",
)