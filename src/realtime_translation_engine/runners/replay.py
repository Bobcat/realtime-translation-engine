from __future__ import annotations

from dataclasses import replace
import time

from ..core import TranslationCore
from ..source import SourceEvent
from ..source import SourceTranscriptState
from ..translator import TranslationMetrics
from ..translator import Translator
from ..types import TranslationDecision
from ..types import TranslationOpportunity


class ReplayRunner:
    def __init__(
        self,
        *,
        translator: Translator,
        core: TranslationCore | None = None,
        commit_correction_enabled: bool = True,
        commit_correction_prompt: str | None = None,
        no_translator_mode: bool = False,
    ) -> None:
        self.translator = translator
        self.core = core or TranslationCore()
        self.commit_correction_enabled = commit_correction_enabled
        self.commit_correction_prompt = commit_correction_prompt
        self.no_translator_mode = no_translator_mode

    @property
    def target_state(self):
        return self.core.target_state

    def set_translator(self, translator: Translator) -> None:
        self.translator = translator

    def reset(self) -> None:
        self.core.reset()

    def handle_event(
        self,
        event: SourceEvent,
        source_state: SourceTranscriptState,
    ) -> TranslationDecision:
        step = self.core.on_source_event(event, source_state)
        opportunity = step.opportunity
        if opportunity is None:
            return TranslationDecision(triggered=False, reason=step.reason)
        if self.no_translator_mode:
            return self._handle_passthrough_opportunity(opportunity)
        return self._handle_translation_opportunity(opportunity)

    def _handle_passthrough_opportunity(
        self,
        opportunity: TranslationOpportunity,
    ) -> TranslationDecision:
        self.core.mark_opportunity_dispatched(opportunity)

        request_id = ""
        correction_model = ""
        metrics = TranslationMetrics()
        output_text = opportunity.source_window

        if opportunity.lane == "preview":
            reason = "preview_event_passthrough"
        elif not opportunity.commits_target:
            reason = "committed_event_passthrough_preview"
        elif self.commit_correction_enabled:
            started = time.perf_counter()
            revised = self.translator.revise_translation(
                opportunity.source_window,
                opportunity.source_window,
                system_prompt=self.commit_correction_prompt,
            )
            output_text = revised.text
            request_id = revised.request_id
            correction_model = revised.model
            replay_request_wall_ms = (time.perf_counter() - started) * 1000.0
            metrics = replace(
                revised.metrics,
                replay_request_wall_ms=replay_request_wall_ms,
                observed_first_text_ms=replay_request_wall_ms,
                observed_complete_ms=replay_request_wall_ms,
            )
            reason = "committed_event_passthrough_revised"
        else:
            reason = "committed_event_passthrough"

        self.core.apply_result(opportunity, output_text)
        return TranslationDecision(
            triggered=True,
            reason=reason,
            source_window=opportunity.source_window,
            target_preview_text=self.target_state.target_preview_text,
            source_chunks_used=opportunity.source_chunks_used,
            request_id=request_id,
            correction_model=correction_model,
            metrics=metrics,
        )

    def _handle_translation_opportunity(
        self,
        opportunity: TranslationOpportunity,
    ) -> TranslationDecision:
        self.core.mark_opportunity_dispatched(opportunity)

        started = time.perf_counter()
        translation = self.translator.translate(opportunity.source_window)
        first_pass_model = translation.model
        final_translation = translation
        correction_model = ""

        if opportunity.lane == "commit" and opportunity.commits_target and self.commit_correction_enabled:
            final_translation = self.translator.revise_translation(
                opportunity.source_window,
                translation.text,
                system_prompt=self.commit_correction_prompt,
            )
            correction_model = final_translation.model

        replay_request_wall_ms = (time.perf_counter() - started) * 1000.0
        self.core.apply_result(opportunity, final_translation.text)
        metrics = replace(
            final_translation.metrics,
            replay_request_wall_ms=replay_request_wall_ms,
            observed_first_text_ms=replay_request_wall_ms,
            observed_complete_ms=replay_request_wall_ms,
        )
        return TranslationDecision(
            triggered=True,
            reason=(
                "preview_event_translated"
                if opportunity.lane == "preview"
                else "committed_event_translated"
            ),
            source_window=opportunity.source_window,
            target_preview_text=self.target_state.target_preview_text,
            source_chunks_used=opportunity.source_chunks_used,
            request_id=final_translation.request_id,
            model=final_translation.model,
            first_pass_model=first_pass_model,
            correction_model=correction_model,
            metrics=metrics,
        )
