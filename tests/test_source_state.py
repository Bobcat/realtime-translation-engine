from __future__ import annotations

import unittest

from realtime_translation_engine import SourceEvent
from realtime_translation_engine import SourceTranscriptState


class SourceTranscriptStateTests(unittest.TestCase):
    def test_preview_replaces_existing_preview_state(self) -> None:
        state = SourceTranscriptState()
        state.apply_event(SourceEvent(kind="p", text="first", line_number=1))
        state.apply_event(SourceEvent(kind="p", text="second", line_number=2))
        self.assertEqual(state.source_preview_text, "second")

    def test_committed_event_appends_committed_state_and_chunk_list(self) -> None:
        state = SourceTranscriptState()
        state.apply_event(SourceEvent(kind="c", text="Hello.", line_number=1))
        state.apply_event(SourceEvent(kind="c", text=" How are you?", line_number=2))
        self.assertEqual(state.source_committed_text, "Hello. How are you?")
        self.assertEqual(state.committed_chunks, ["Hello.", " How are you?"])

    def test_committed_event_inserts_space_after_sentence_boundary_when_missing(self) -> None:
        state = SourceTranscriptState()
        state.apply_event(SourceEvent(kind="c", text="Hello.", line_number=1))
        state.apply_event(SourceEvent(kind="c", text="How are you?", line_number=2))
        self.assertEqual(state.source_committed_text, "Hello. How are you?")
        self.assertEqual(state.committed_chunks, ["Hello.", "How are you?"])

    def test_committed_event_inserts_space_after_comma_when_missing(self) -> None:
        state = SourceTranscriptState()
        state.apply_event(SourceEvent(kind="c", text="Hello,", line_number=1))
        state.apply_event(SourceEvent(kind="c", text="world", line_number=2))
        self.assertEqual(state.source_committed_text, "Hello, world")
        self.assertEqual(state.committed_chunks, ["Hello,", "world"])


if __name__ == "__main__":
    unittest.main()
