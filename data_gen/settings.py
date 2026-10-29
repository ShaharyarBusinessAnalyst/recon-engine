from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class GenSettings:
    seed: int = 42
    output_dir: Path = Path("data/generated")
    n_items: int = 150
    start_date: date = date(2024, 1, 1)
    end_date: date = date(2026, 1, 1)
