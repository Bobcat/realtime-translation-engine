from __future__ import annotations

from ..core import TranslationCore
from ..source import SourceEvent
from ..source import SourceTranscriptState
from ..types import LiveDispatchRequest
from ..types import LiveRunnerStep


class LiveRunner:
    def __init__(self, *, core: TranslationCore | None = None) -> None:
        self.core = core or TranslationCore()
        self._next_request_id = 1
        self._committed_target_base_revision = 0
        self._inflight_request: LiveDispatchRequest | None = None
        self._commit_needed = False
        self._pending_preview_text = ""

    @property
    def target_state(self):
        return self.core.target_state

    def reset(self) -> None:
        self.core.reset()
        self._next_request_id = 1
        self._committed_target_base_revision = 0
        self._inflight_request = None
        self._commit_needed = False
        self._pending_preview_text = ""

    def retire_inflight(self) -> bool:
        if self._inflight_request is None:
            self._commit_needed = False
            self._pending_preview_text = ""
            return False
        self._inflight_request = None
        self._commit_needed = False
        self._pending_preview_text = ""
        return True

    def on_source_event(
        self,
        event: SourceEvent,
        source_state: SourceTranscriptState,
    ) -> LiveRunnerStep:
        step = self.core.on_source_event(event, source_state)
        opportunity = step.opportunity
        if opportunity is not None:
            if opportunity.lane == "commit":
                self._commit_needed = True
                self._pending_preview_text = ""
            else:
                self._pending_preview_text = opportunity.source_preview_text
        return self._maybe_dispatch(step.reason)

    def on_llm_result(
        self,
        request: LiveDispatchRequest,
        translated_text: str,
    ) -> LiveRunnerStep:
        if self._inflight_request is None:
            raise ValueError("No live translation request is in flight.")
        if request.request_id != self._inflight_request.request_id:
            raise ValueError(
                f"Result request_id {request.request_id} does not match inflight request_id "
                f"{self._inflight_request.request_id}."
            )

        self._inflight_request = None
        applied = False

        if request.opportunity.lane == "preview":
            if request.committed_target_base_revision == self._committed_target_base_revision:
                self.core.apply_result(request.opportunity, translated_text)
                applied = True
                reason = "preview_result_applied"
            else:
                reason = "preview_result_incompatible"
        else:
            if request.committed_target_base_revision != self._committed_target_base_revision:
                reason = "commit_result_stale"
            else:
                self.core.apply_result(request.opportunity, translated_text)
                applied = True
                reason = "commit_result_applied"
                if request.opportunity.commits_target:
                    self._committed_target_base_revision += 1

        next_step = self._maybe_dispatch(reason)
        return LiveRunnerStep(
            reason=reason,
            dispatch_request=next_step.dispatch_request,
            result_applied=applied,
        )

    def _maybe_dispatch(self, reason: str) -> LiveRunnerStep:
        if self._inflight_request is not None:
            return LiveRunnerStep(reason=reason)

        opportunity = None
        if self._commit_needed:
            self._commit_needed = False
            opportunity = self.core.build_commit_opportunity()
        elif self._pending_preview_text:
            preview_text = self._pending_preview_text
            self._pending_preview_text = ""
            opportunity = self.core.build_preview_opportunity(preview_text)

        if opportunity is None:
            return LiveRunnerStep(reason=reason)

        self.core.mark_opportunity_dispatched(opportunity)
        request = LiveDispatchRequest(
            request_id=self._next_request_id,
            committed_target_base_revision=self._committed_target_base_revision,
            opportunity=opportunity,
        )
        self._next_request_id += 1
        self._inflight_request = request
        return LiveRunnerStep(
            reason="dispatch_ready",
            dispatch_request=request,
        )
