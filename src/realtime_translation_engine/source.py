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
            self.source_committed_text = _append_committed_source_text(
                self.source_committed_text,
                event.text,
            )
            self.committed_chunks.append(event.text)
            self.source_preview_text = ""
            return
        raise ValueError(f"unsupported event kind: {event.kind!r}")


def append_source_text(existing: str, addition: str) -> str:
    if addition == "":
        return existing
    if existing == "":
        return addition
    if existing.endswith((" ", "\n", "\t")) or addition.startswith((" ", "\n", "\t")):
        return existing + addition
    if existing.rstrip().endswith((".", ",", "?", "!")) and addition[:1] not in '.,?!:;)]}"\'':
        return f"{existing} {addition}"
    return existing + addition


def assemble_source_text(parts: list[str]) -> str:
    assembled = ""
    for part in parts:
        assembled = append_source_text(assembled, part)
    return assembled


def _append_committed_source_text(existing: str, addition: str) -> str:
    return append_source_text(existing, addition)
