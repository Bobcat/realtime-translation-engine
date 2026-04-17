from __future__ import annotations

from .config import PreviewTranslationSettings
from .source import assemble_source_text
from .source import SourceEvent
from .source import SourceTranscriptState
from .types import CoreEventResult
from .types import TargetTranscriptState
from .types import TranslationOpportunity


class TranslationCore:
    def __init__(
        self,
        *,
        preview_settings: PreviewTranslationSettings | None = None,
    ) -> None:
        self.preview_settings = preview_settings or PreviewTranslationSettings()
        self.target_state = TargetTranscriptState()
        self.open_source_chunks: list[str] = []
        self.open_source_chunk_boundaries: list[bool] = []
        self.previous_source_preview_text = ""
        self.last_dispatched_source_preview_text = ""

    def on_source_event(
        self,
        event: SourceEvent,
        source_state: SourceTranscriptState,
    ) -> CoreEventResult:
        if event.kind == "p":
            return self._on_preview_event(source_state)
        if event.kind == "c":
            return self._on_committed_event(event, source_state)
        return CoreEventResult(reason="unsupported_event_kind")

    def mark_opportunity_dispatched(self, opportunity: TranslationOpportunity) -> None:
        if opportunity.lane != "preview":
            return
        self.last_dispatched_source_preview_text = opportunity.source_preview_text

    def apply_result(self, opportunity: TranslationOpportunity, translated_text: str) -> None:
        if opportunity.lane == "preview":
            self.target_state.target_preview_text = translated_text
            return
        if opportunity.commits_target:
            self.target_state.target_committed_text = _append_transcript_text(
                self.target_state.target_committed_text,
                translated_text,
            )
            self.target_state.target_preview_text = ""
            del self.open_source_chunks[: opportunity.source_chunks_used]
            del self.open_source_chunk_boundaries[: opportunity.source_chunks_used]
            return
        self.target_state.target_preview_text = translated_text

    def build_commit_opportunity(self) -> TranslationOpportunity | None:
        source_window = self._build_source_window()
        if source_window == "":
            return None
        commits_target = False
        if self.open_source_chunk_boundaries:
            commits_target = self.open_source_chunk_boundaries[-1]
        return TranslationOpportunity(
            lane="commit",
            source_window=source_window,
            source_chunks_used=len(self.open_source_chunks),
            commits_target=commits_target,
        )

    def build_preview_opportunity(self, source_preview_text: str) -> TranslationOpportunity | None:
        source_window = self._build_preview_source_window(source_preview_text)
        if source_window == "":
            return None
        return TranslationOpportunity(
            lane="preview",
            source_window=source_window,
            source_chunks_used=len(self.open_source_chunks) + 1,
            source_preview_text=source_preview_text,
        )

    def reset(self) -> None:
        self.target_state = TargetTranscriptState()
        self.open_source_chunks.clear()
        self.open_source_chunk_boundaries.clear()
        self._reset_preview_run_state()

    def _on_committed_event(
        self,
        event: SourceEvent,
        source_state: SourceTranscriptState,
    ) -> CoreEventResult:
        self.open_source_chunks.append(event.text)
        self.open_source_chunk_boundaries.append(_ends_with_sentence_boundary(event.text))
        self._reset_preview_run_state()
        opportunity = self.build_commit_opportunity()
        if opportunity is None:
            return CoreEventResult(reason="empty_committed_window")
        return CoreEventResult(reason="committed_event_ready", opportunity=opportunity)

    def _on_preview_event(self, source_state: SourceTranscriptState) -> CoreEventResult:
        preview_text = source_state.source_preview_text
        trimmed_preview = preview_text.rstrip()
        if trimmed_preview == "":
            self._reset_preview_run_state()
            return CoreEventResult(reason="empty_preview")

        previous_preview = self.previous_source_preview_text.rstrip()
        self.previous_source_preview_text = preview_text
        if not self.preview_settings.enabled:
            return CoreEventResult(reason="preview_translation_disabled")
        if previous_preview == "":
            return CoreEventResult(reason="preview_needs_previous_sample")
        if len(trimmed_preview) < self.preview_settings.min_chars:
            return CoreEventResult(reason="preview_below_min_chars")

        distance_ratio = _edit_distance_ratio(previous_preview, trimmed_preview)
        if distance_ratio > self.preview_settings.max_distance_ratio:
            return CoreEventResult(reason="preview_unstable")

        growth = max(
            0,
            len(trimmed_preview) - len(self.last_dispatched_source_preview_text.rstrip()),
        )
        if growth < self.preview_settings.min_growth_chars:
            return CoreEventResult(reason="preview_not_grown_enough")

        opportunity = self.build_preview_opportunity(preview_text)
        if opportunity is None:
            return CoreEventResult(reason="empty_preview_window")

        return CoreEventResult(reason="preview_event_ready", opportunity=opportunity)

    def _build_source_window(self) -> str:
        chunks = [chunk for chunk in self.open_source_chunks if chunk]
        if not chunks:
            return ""
        return assemble_source_text(chunks)

    def _build_preview_source_window(self, source_preview_text: str) -> str:
        parts = [chunk for chunk in self.open_source_chunks if chunk]
        if source_preview_text.strip():
            parts.append(source_preview_text)
        if not parts:
            return ""
        return assemble_source_text(parts)

    def _reset_preview_run_state(self) -> None:
        self.previous_source_preview_text = ""
        self.last_dispatched_source_preview_text = ""


def _ends_with_sentence_boundary(text: str) -> bool:
    stripped = text.rstrip()
    if stripped == "":
        return False
    return stripped[-1] in ".?!"


def _append_transcript_text(existing: str, addition: str) -> str:
    if addition == "":
        return existing
    if existing == "":
        return addition
    if existing.endswith((" ", "\n")) or addition.startswith((" ", "\n")):
        return existing + addition
    return f"{existing} {addition}"


def _edit_distance_ratio(left: str, right: str) -> float:
    return _edit_distance(left, right) / max(len(left), len(right), 1)


def _edit_distance(left: str, right: str) -> int:
    right_len = len(right)
    previous = list(range(right_len + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index] + [0] * right_len
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current[right_index] = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
        previous = current
    return previous[right_len]
