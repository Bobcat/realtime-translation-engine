# Realtime Translation Engine Package Note

## Purpose

This note complements `event-driven-translation-engine-note.md`.

The original note stays high-level and behavior-focused.
This note records the concrete package boundary and implementation direction.

## Package Name

Repository name:

- `realtime-translation-engine`

Python import path:

- `realtime_translation_engine`

## Relationship To The Existing Workbench

The package extracts the reusable translation engine from the current
workbench backend.

The workbench remains an application.
The package becomes a reusable engine dependency.

## Current Internal Engine Shape

The current internal engine lives under:

- `app/realtime_translation_engine/__init__.py`
- `app/realtime_translation_engine/core.py`
- `app/realtime_translation_engine/replay_runner.py`
- `app/realtime_translation_engine/live_runner.py`
- `app/realtime_translation_engine/types.py`

This is the starting point for extraction.

## Current Responsibilities

### Translation Core

The core:

- ingests `p` and `c` source events
- maintains target transcript state
- tracks committed source chunks relevant for translation coverage
- determines whether a source event yields:
  - no opportunity
  - a preview opportunity
  - a commit opportunity
- applies completed translation results back into target state

Implementation entrypoint:

- `core.py`

### Replay Runner

The replay runner:

- submits each source event to the core immediately
- dispatches each emitted opportunity immediately
- blocks further event progression while the translation call runs
- applies the result immediately back into the core

Implementation entrypoint:

- `replay_runner.py`

### Live Runner

The live runner:

- submits every source event to the core immediately
- keeps ingestion non-blocking
- assumes one serialized in-flight translation request
- prioritizes commit work over preview work
- keeps preview as intent rather than preserving a queue of old preview requests
- applies preview results only when committed-base compatibility still holds

Implementation entrypoint:

- `live_runner.py`

## Current Types

Current engine types:

- `TargetTranscriptState`
- `TranslationOpportunity`
- `CoreEventResult`
- `LiveDispatchRequest`
- `LiveRunnerStep`
- `TranslationDecision`

Definitions:

- `types.py`

## Package Boundary

The package contains:

- translation core
- replay runner
- live runner
- engine types
- engine config types
- translation eligibility / gating configuration

The package does not contain application concerns, including:

- transport and API integration
- session orchestration
- prompt storage and prompt library management
- model administration
- workbench-specific UI concerns

## Prompt Inputs

Prompt files and prompt storage remain application-level assets.

The package receives concrete prompt content through configuration.

The package receives:

- `first_pass.system_prompt`
- `first_pass.user_prompt`
- `second_pass.system_prompt`
- `second_pass.user_prompt`

## Settings File Boundary

Settings files are application responsibility.

- applications keep their own settings files or other config sources
- the package does not require reading any settings file directly

The package does not depend on:

- a repo-local settings file
- a hard-coded file layout

## Configuration Direction

The package exposes public configuration for at least these areas:

### First Pass

- model
- system prompt
- user prompt

### Second Pass

- enabled or disabled
- model
- system prompt
- user prompt

Package/config naming uses:

- `first_pass`
- `second_pass`

### Translation Eligibility / Gating

The package exposes configuration for at least:

- preview enabled
- preview minimum chars
- preview minimum growth chars
- preview maximum distance ratio

These settings are:

- configurable by the application
- inspectable by the application

### Optional Decoding Settings

The package may expose optional decoding settings for translator requests.

## Runtime Mutability

The package supports application-driven runtime updates of meaningful configuration.

- config belongs to the engine and runners
- the application is allowed to inspect and update relevant settings

## Remaining Extraction Blockers

The current internal engine is close to extraction, but not fully package-clean yet.

### Host-Specific Type Imports

The engine currently still imports application-level types from the existing app:

- `core.py` imports `PreviewTranslationSettings` from the application replay settings module
- the engine also currently depends on:
  - the application events module
  - the application source state module

Before extraction, these package-facing concepts must be owned by the package itself
or replaced by package-native equivalents.

### Translator Boundary

The engine/runners currently assume the existing translator interfaces from:

- the current application translator module

Before extraction, the package must define its own translator interface instead of
depending on the application module directly.
