from __future__ import annotations

import unittest

from realtime_translation_engine import LiveRunner
from realtime_translation_engine import PreviewTranslationSettings
from realtime_translation_engine import SourceEvent
from realtime_translation_engine import SourceTranscriptState
from realtime_translation_engine import TranslationCore


class LiveRunnerTests(unittest.TestCase):
    def test_preview_intent_dispatches_after_inflight_commit_finishes(self) -> None:
        core = TranslationCore(
            preview_settings=PreviewTranslationSettings(
                enabled=True,
                min_chars=5,
                max_distance_ratio=1.0,
                min_growth_chars=5,
            )
        )
        runner = LiveRunner(core=core)
        source_state = SourceTranscriptState()

        first_commit = SourceEvent(kind="c", text="Hello.", line_number=1)
        source_state.apply_event(first_commit)
        first_step = runner.on_source_event(first_commit, source_state)
        self.assertIsNotNone(first_step.dispatch_request)
        first_request = first_step.dispatch_request
        assert first_request is not None
        self.assertEqual(first_request.opportunity.lane, "commit")

        preview_1 = SourceEvent(kind="p", text=" worl", line_number=2)
        source_state.apply_event(preview_1)
        step = runner.on_source_event(preview_1, source_state)
        self.assertIsNone(step.dispatch_request)

        preview_2 = SourceEvent(kind="p", text=" world", line_number=3)
        source_state.apply_event(preview_2)
        step = runner.on_source_event(preview_2, source_state)
        self.assertIsNone(step.dispatch_request)

        result_step = runner.on_llm_result(first_request, "Hallo.")
        self.assertTrue(result_step.result_applied)
        self.assertEqual(runner.target_state.target_committed_text, "Hallo.")
        self.assertIsNotNone(result_step.dispatch_request)
        preview_request = result_step.dispatch_request
        assert preview_request is not None
        self.assertEqual(preview_request.opportunity.lane, "preview")
        self.assertEqual(preview_request.opportunity.source_window, " world")

    def test_new_commit_drops_unsent_preview_intent(self) -> None:
        core = TranslationCore(
            preview_settings=PreviewTranslationSettings(
                enabled=True,
                min_chars=5,
                max_distance_ratio=1.0,
                min_growth_chars=5,
            )
        )
        runner = LiveRunner(core=core)
        source_state = SourceTranscriptState()

        first_commit = SourceEvent(kind="c", text="Hello.", line_number=1)
        source_state.apply_event(first_commit)
        first_request = runner.on_source_event(first_commit, source_state).dispatch_request
        assert first_request is not None

        preview_1 = SourceEvent(kind="p", text=" worl", line_number=2)
        source_state.apply_event(preview_1)
        runner.on_source_event(preview_1, source_state)

        preview_2 = SourceEvent(kind="p", text=" world", line_number=3)
        source_state.apply_event(preview_2)
        runner.on_source_event(preview_2, source_state)

        second_commit = SourceEvent(kind="c", text=" Next.", line_number=4)
        source_state.apply_event(second_commit)
        runner.on_source_event(second_commit, source_state)

        result_step = runner.on_llm_result(first_request, "Hallo.")
        self.assertTrue(result_step.result_applied)
        self.assertIsNotNone(result_step.dispatch_request)
        second_request = result_step.dispatch_request
        assert second_request is not None
        self.assertEqual(second_request.opportunity.lane, "commit")
        self.assertEqual(second_request.opportunity.source_window, " Next.")

    def test_commit_work_is_rematerialized_from_current_open_chunks(self) -> None:
        runner = LiveRunner(core=TranslationCore())
        source_state = SourceTranscriptState()

        first_commit = SourceEvent(kind="c", text="Hello.", line_number=1)
        source_state.apply_event(first_commit)
        first_request = runner.on_source_event(first_commit, source_state).dispatch_request
        assert first_request is not None
        self.assertEqual(first_request.opportunity.source_window, "Hello.")

        second_commit = SourceEvent(kind="c", text=" Next.", line_number=2)
        source_state.apply_event(second_commit)
        runner.on_source_event(second_commit, source_state)

        result_step = runner.on_llm_result(first_request, "Hallo.")
        self.assertIsNotNone(result_step.dispatch_request)
        second_request = result_step.dispatch_request
        assert second_request is not None
        self.assertEqual(second_request.opportunity.source_window, " Next.")
        self.assertEqual(second_request.opportunity.source_chunks_used, 1)

    def test_preview_result_is_shown_before_following_commit_dispatch(self) -> None:
        core = TranslationCore(
            preview_settings=PreviewTranslationSettings(
                enabled=True,
                min_chars=5,
                max_distance_ratio=1.0,
                min_growth_chars=5,
            )
        )
        runner = LiveRunner(core=core)
        source_state = SourceTranscriptState()

        preview_1 = SourceEvent(kind="p", text=" worl", line_number=1)
        source_state.apply_event(preview_1)
        step = runner.on_source_event(preview_1, source_state)
        self.assertIsNone(step.dispatch_request)

        preview_2 = SourceEvent(kind="p", text=" world", line_number=2)
        source_state.apply_event(preview_2)
        preview_request = runner.on_source_event(preview_2, source_state).dispatch_request
        assert preview_request is not None
        self.assertEqual(preview_request.opportunity.lane, "preview")

        commit_event = SourceEvent(kind="c", text="Hello.", line_number=3)
        source_state.apply_event(commit_event)
        step = runner.on_source_event(commit_event, source_state)
        self.assertIsNone(step.dispatch_request)

        result_step = runner.on_llm_result(preview_request, "Hallo wereld")
        self.assertTrue(result_step.result_applied)
        self.assertEqual(runner.target_state.target_preview_text, "Hallo wereld")
        self.assertIsNotNone(result_step.dispatch_request)
        commit_request = result_step.dispatch_request
        assert commit_request is not None
        self.assertEqual(commit_request.opportunity.lane, "commit")


if __name__ == "__main__":
    unittest.main()
