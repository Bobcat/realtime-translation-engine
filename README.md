# Realtime Translation Engine

`realtime-translation-engine` is a reusable event-driven engine for incremental, LLM-based translation.

Applications produce source events. Source events are incremental text updates, such as preview text and committed text. The engine ingests those events, applies translation gating, decides when to issue new translation requests to an LLM, and maintains preview and committed target state over time.

The package also includes translator implementations under `realtime_translation_engine.translators`.

## Package Exports

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
- `realtime_translation_engine.translators`

## Responsibilities

The engine is responsible for:

- ingesting source events
- applying translation gating
- deciding when new translation work should be issued
- maintaining preview and committed target state
- supporting replay-style and live-style runner behavior

The application is responsible for:

- producing source events
- choosing prompts and models
- handling sessions and application UI

## Runners

- `ReplayRunner`  
  Processes source events one by one. When it issues a translation request, it waits for the result before continuing.

- `LiveRunner`  
  Continues ingesting source events while translation work is in flight. Commit work takes priority and preview is best-effort.

Both runners use the same `TranslationCore`.

## LLM Integration

Translation requests are executed through the `Translator` interface.

This package includes a concrete `Translator` implementation using [llm-pool](https://github.com/Bobcat/llm-pool), under `realtime_translation_engine.translators`.

## Design Notes

- [Event-Driven Translation Engine Note](docs/event-driven-translation-engine-note.md)
- [Realtime Translation Engine Package Note](docs/realtime-translation-engine-package-note.md)

## Local Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest tests.test_core tests.test_live_runner tests.test_source_state tests.test_translators
```

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
