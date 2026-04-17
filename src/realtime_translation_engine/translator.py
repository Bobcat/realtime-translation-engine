from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol


class Translator(Protocol):
    def translate(self, source_window: str) -> "TranslationResult":
        ...

    def revise_translation(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> "TranslationResult":
        ...


@dataclass(frozen=True)
class TranslationMetrics:
    replay_request_wall_ms: float | None = None
    observed_first_text_ms: float | None = None
    observed_complete_ms: float | None = None
    transport_first_byte_ms: float | None = None
    transport_first_text_delta_ms: float | None = None
    transport_completed_ms: float | None = None
    engine_tokenize_ms: float | None = None
    gpu_time_to_first_token_ms: float | None = None
    gpu_generate_total_ms: float | None = None
    gpu_decode_after_first_token_ms: float | None = None
    engine_prompt_tokens: int | None = None
    engine_output_tokens: int | None = None
    engine_tokens_per_second: float | None = None


@dataclass(frozen=True)
class TranslationResult:
    text: str
    request_id: str = ""
    model: str = ""
    metrics: TranslationMetrics = field(default_factory=TranslationMetrics)
