# Realtime Translation Engine

`realtime-translation-engine` is a reusable event-driven engine for incremental, LLM-based translation.

Applications produce source events. Source events are incremental text updates, such as preview text and committed text. The engine ingests those events, applies translation gating, decides when to issue new translation requests to an LLM, and maintains preview and committed target state over time.

Applications also provide the translator component that actually sends those requests to the LLM and returns the results.

## Package Surface

The package exposes:

- `TranslationCore`
- `ReplayRunner`
- `LiveRunner`
- `SourceEvent`
- `SourceTranscriptState`
- `PreviewTranslationSettings`
- `Translator`
- `TranslationResult`
- `TranslationMetrics`

## Responsibilities

The engine is responsible for:

- ingesting source events
- applying translation gating
- deciding when new translation work should be issued
- maintaining preview and committed target state
- supporting replay-style and live-style runner behavior

The application is responsible for:

- producing source events
- providing the translator integration that talks to the LLM
- choosing prompts and models
- handling transport, sessions, and application UI

## Runners

- `ReplayRunner`  
  Processes source events one by one. When it issues a translation request, it waits for the result before continuing.

- `LiveRunner`  
  Continues ingesting source events while translation work is in flight. Commit work takes priority and preview is best-effort.

Both runners use the same `TranslationCore`.

## Out of Scope

This package does not contain:

- transport or API integration
- session orchestration
- prompt storage or prompt library management
- model loading or model administration
- application-specific UI concerns

## Design Notes

- [Event-Driven Translation Engine Note](docs/event-driven-translation-engine-note.md)
- [Realtime Translation Engine Package Note](docs/realtime-translation-engine-package-note.md)

## Local Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest tests.test_core tests.test_live_runner tests.test_source_state
```
