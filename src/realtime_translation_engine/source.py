from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class SourceEvent:
    kind: str
    text: str
    line_number: int


@dataclass
class SourceTranscriptState:
    source_committed_text: str = ""
    source_preview_text: str = ""
    committed_chunks: list[str] = field(default_factory=list)

    def apply_event(self, event: SourceEvent) -> None:
        if event.kind == "p":
            self.source_preview_text = event.text
            return
        if event.kind == "c":
            self.source_committed_text += event.text
            self.committed_chunks.append(event.text)
            self.source_preview_text = ""
            return
        raise ValueError(f"unsupported event kind: {event.kind!r}")
