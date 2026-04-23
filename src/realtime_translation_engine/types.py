from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from .translator import TranslationMetrics


@dataclass
class TargetTranscriptState:
    target_committed_text: str = ""
    target_preview_text: str = ""


@dataclass(frozen=True)
class TranslationOpportunity:
    lane: Literal["preview", "commit"]
    source_window: str
    source_chunks_used: int
    source_preview_text: str = ""
    commits_target: bool = False


@dataclass(frozen=True)
class CoreEventResult:
    reason: str
    opportunity: TranslationOpportunity | None = None


@dataclass(frozen=True)
class LiveDispatchRequest:
    request_id: int
    committed_target_base_revision: int
    opportunity: TranslationOpportunity


@dataclass(frozen=True)
class LiveRunnerStep:
    reason: str
    dispatch_request: LiveDispatchRequest | None = None
    result_applied: bool = False


@dataclass
class TranslationDecision:
    triggered: bool
    reason: str
    source_window: str = ""
    target_preview_text: str = ""
    source_chunks_used: int = 0
    request_id: str = ""
    model: str = ""
    first_pass_model: str = ""
    second_pass_model: str = ""
    metrics: TranslationMetrics = field(default_factory=TranslationMetrics)
