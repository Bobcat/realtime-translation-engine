from __future__ import annotations

import unittest

from realtime_translation_engine import PreviewTranslationSettings
from realtime_translation_engine import ReplayRunner
from realtime_translation_engine import SourceEvent
from realtime_translation_engine import SourceTranscriptState
from realtime_translation_engine import TranslationCore
from realtime_translation_engine import TranslationResult
from realtime_translation_engine import Translator


class RecordingTranslator(Translator):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def translate(self, source_window: str) -> TranslationResult:
        self.calls.append(source_window)
        return TranslationResult(text=f"T::{source_window}", model="recording")

    def run_second_pass(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> TranslationResult:
        del source_window
        del system_prompt
        return TranslationResult(text=draft_translation, model="recording")


class WindowTranslator(Translator):
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def translate(self, source_window: str) -> TranslationResult:
        self.calls.append(source_window)
        return TranslationResult(text=self.mapping[source_window], model="window")

    def run_second_pass(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> TranslationResult:
        del source_window
        del system_prompt
        return TranslationResult(text=draft_translation, model="window")


class SecondPassTranslator(Translator):
    def __init__(self) -> None:
        self.translate_calls: list[str] = []
        self.second_pass_calls: list[tuple[str, str, str | None]] = []

    def translate(self, source_window: str) -> TranslationResult:
        self.translate_calls.append(source_window)
        return TranslationResult(text=f"DRAFT::{source_window}", model="first-pass")

    def run_second_pass(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> TranslationResult:
        self.second_pass_calls.append((source_window, draft_translation, system_prompt))
        return TranslationResult(text=f"FINAL::{draft_translation}", model="second-pass")


class TranslationCoreTests(unittest.TestCase):
    def test_committed_source_event_clears_preview_state(self) -> None:
        source_state = SourceTranscriptState()

        source_state.apply_event(SourceEvent(kind="p", text="preview", line_number=1))
        source_state.apply_event(SourceEvent(kind="c", text="final", line_number=2))

        self.assertEqual(source_state.source_committed_text, "final")
        self.assertEqual(source_state.source_preview_text, "")

    def test_translation_core_only_triggers_on_committed_events(self) -> None:
        translator = RecordingTranslator()
        runner = ReplayRunner(translator=translator)
        source_state = SourceTranscriptState()

        preview_event = SourceEvent(kind="p", text="preview", line_number=1)
        source_state.apply_event(preview_event)
        preview_decision = runner.handle_event(preview_event, source_state)

        committed_event = SourceEvent(kind="c", text="Hello.", line_number=2)
        source_state.apply_event(committed_event)
        committed_decision = runner.handle_event(committed_event, source_state)

        self.assertFalse(preview_decision.triggered)
        self.assertTrue(committed_decision.triggered)
        self.assertEqual(translator.calls, ["Hello."])

    def test_source_window_uses_open_source_chunks_until_boundary(self) -> None:
        translator = RecordingTranslator()
        runner = ReplayRunner(translator=translator)
        source_state = SourceTranscriptState()

        first_event = SourceEvent(kind="c", text="one", line_number=1)
        source_state.apply_event(first_event)
        first_decision = runner.handle_event(first_event, source_state)

        second_event = SourceEvent(kind="c", text=" two", line_number=2)
        source_state.apply_event(second_event)
        second_decision = runner.handle_event(second_event, source_state)

        third_event = SourceEvent(kind="c", text=" three.", line_number=3)
        source_state.apply_event(third_event)
        third_decision = runner.handle_event(third_event, source_state)

        self.assertTrue(first_decision.triggered)
        self.assertEqual(first_decision.source_window, "one")
        self.assertEqual(first_decision.source_chunks_used, 1)
        self.assertEqual(second_decision.source_window, "one two")
        self.assertEqual(second_decision.source_chunks_used, 2)
        self.assertEqual(third_decision.source_window, "one two three.")
        self.assertEqual(third_decision.source_chunks_used, 3)
        self.assertEqual(translator.calls, ["one", "one two", "one two three."])

    def test_target_state_commits_only_on_source_sentence_boundary(self) -> None:
        translator = WindowTranslator(
            {
                "Hello": "Hallo",
                "Hello world.": "Hallo wereld.",
                " How are": "Hoe gaat",
                " How are you?": "Hoe gaat het?",
            }
        )
        core = TranslationCore()
        runner = ReplayRunner(translator=translator, core=core)
        source_state = SourceTranscriptState()

        first_event = SourceEvent(kind="c", text="Hello", line_number=1)
        source_state.apply_event(first_event)
        first_decision = runner.handle_event(first_event, source_state)

        second_event = SourceEvent(kind="c", text=" world.", line_number=2)
        source_state.apply_event(second_event)
        second_decision = runner.handle_event(second_event, source_state)

        third_event = SourceEvent(kind="c", text=" How are", line_number=3)
        source_state.apply_event(third_event)
        third_decision = runner.handle_event(third_event, source_state)

        fourth_event = SourceEvent(kind="c", text=" you?", line_number=4)
        source_state.apply_event(fourth_event)
        fourth_decision = runner.handle_event(fourth_event, source_state)

        self.assertEqual(first_decision.target_preview_text, "Hallo")
        self.assertEqual(second_decision.target_preview_text, "")
        self.assertEqual(third_decision.target_preview_text, "Hoe gaat")
        self.assertEqual(fourth_decision.target_preview_text, "")
        self.assertEqual(runner.target_state.target_committed_text, "Hallo wereld. Hoe gaat het?")
        self.assertEqual(runner.target_state.target_preview_text, "")
        self.assertEqual(
            translator.calls,
            ["Hello", "Hello world.", " How are", " How are you?"],
        )

    def test_preview_event_translates_when_preview_is_stable_and_long_enough(self) -> None:
        translator = WindowTranslator(
            {
                "Hello": "Hallo",
                "Hello world and more text": "Hallo wereld en meer tekst",
            }
        )
        preview_settings = PreviewTranslationSettings(
            enabled=True,
            min_chars=10,
            max_distance_ratio=0.30,
            min_growth_chars=10,
        )
        core = TranslationCore(preview_settings=preview_settings)
        runner = ReplayRunner(translator=translator, core=core)
        source_state = SourceTranscriptState()

        committed_event = SourceEvent(kind="c", text="Hello", line_number=1)
        source_state.apply_event(committed_event)
        runner.handle_event(committed_event, source_state)

        preview_event_1 = SourceEvent(kind="p", text=" world and more", line_number=2)
        source_state.apply_event(preview_event_1)
        first_preview_decision = runner.handle_event(preview_event_1, source_state)

        preview_event_2 = SourceEvent(kind="p", text=" world and more text", line_number=3)
        source_state.apply_event(preview_event_2)
        second_preview_decision = runner.handle_event(preview_event_2, source_state)

        self.assertFalse(first_preview_decision.triggered)
        self.assertTrue(second_preview_decision.triggered)
        self.assertEqual(second_preview_decision.reason, "preview_event_translated")
        self.assertEqual(second_preview_decision.source_window, "Hello world and more text")
        self.assertEqual(runner.target_state.target_preview_text, "Hallo wereld en meer tekst")
        self.assertEqual(translator.calls, ["Hello", "Hello world and more text"])

    def test_replay_of_small_example_keeps_preview_and_translates_on_c_only(self) -> None:
        events = [
            SourceEvent(kind="p", text="Hel", line_number=1),
            SourceEvent(kind="p", text="Hello", line_number=2),
            SourceEvent(kind="c", text="Hello.", line_number=3),
            SourceEvent(kind="p", text="", line_number=4),
            SourceEvent(kind="p", text="How are you?", line_number=5),
            SourceEvent(kind="c", text=" How are you?", line_number=6),
            SourceEvent(kind="p", text="", line_number=7),
        ]
        translator = RecordingTranslator()
        runner = ReplayRunner(translator=translator)
        source_state = SourceTranscriptState()
        traces = []
        for event in events:
            source_state.apply_event(event)
            traces.append(runner.handle_event(event, source_state))

        self.assertEqual(len(traces), 7)
        self.assertEqual(len(translator.calls), 2)
        self.assertEqual(translator.calls[0], "Hello.")
        self.assertEqual(translator.calls[1], " How are you?")
        self.assertEqual(source_state.source_committed_text, "Hello. How are you?")
        self.assertEqual(source_state.source_preview_text, "")
        self.assertEqual(runner.target_state.target_committed_text, "T::Hello. T:: How are you?")
        self.assertEqual(runner.target_state.target_preview_text, "")

    def test_second_pass_runs_only_on_sentence_boundary(self) -> None:
        translator = SecondPassTranslator()
        runner = ReplayRunner(translator=translator)
        source_state = SourceTranscriptState()

        first_event = SourceEvent(kind="c", text="Hello", line_number=1)
        source_state.apply_event(first_event)
        first_decision = runner.handle_event(first_event, source_state)

        second_event = SourceEvent(kind="c", text=" world.", line_number=2)
        source_state.apply_event(second_event)
        second_decision = runner.handle_event(second_event, source_state)

        self.assertEqual(first_decision.target_preview_text, "DRAFT::Hello")
        self.assertEqual(second_decision.target_preview_text, "")
        self.assertEqual(
            translator.translate_calls,
            ["Hello", "Hello world."],
        )
        self.assertEqual(
            translator.second_pass_calls,
            [("Hello world.", "DRAFT::Hello world.", None)],
        )
        self.assertEqual(
            runner.target_state.target_committed_text,
            "FINAL::DRAFT::Hello world.",
        )
        self.assertEqual(second_decision.model, "second-pass")

    def test_second_pass_can_be_disabled(self) -> None:
        translator = SecondPassTranslator()
        runner = ReplayRunner(
            translator=translator,
            second_pass_enabled=False,
        )
        source_state = SourceTranscriptState()

        first_event = SourceEvent(kind="c", text="Hello", line_number=1)
        source_state.apply_event(first_event)
        runner.handle_event(first_event, source_state)

        second_event = SourceEvent(kind="c", text=" world.", line_number=2)
        source_state.apply_event(second_event)
        second_decision = runner.handle_event(second_event, source_state)

        self.assertEqual(translator.second_pass_calls, [])
        self.assertEqual(second_decision.model, "first-pass")


if __name__ == "__main__":
    unittest.main()
