from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewTranslationSettings:
    enabled: bool = True
    min_chars: int = 80
    max_distance_ratio: float = 0.15
    min_growth_chars: int = 50
