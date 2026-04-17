# Event-Driven Translation Engine Note

## Purpose

This note captures the baseline design for a reusable event-driven translation engine.

The current `translation-replay-dev` backend is useful as a replay workbench, but the real target is broader:

- ingest a stream of transcript events (`p` and `c`)
- maintain translated preview and committed target text
- support both replay and live use cases

The main new requirement for live use is that the engine must not block transcript ingestion on LLM calls.

## Non-Goal

This note does not define:

- HTTP or WebSocket transport
- prompt library CRUD
- replay session management
- file formats as the primary interface

`.pc` remains a useful replay/export format, but it is not the core abstraction.

## Core Idea

The engine should consume transcript events and produce translation state updates, while scheduling translation work asynchronously.

The central distinction is:

- `preview` work is best-effort
- `commit` work is coverage-critical

So the invariant is not:

- "every relevant event becomes an LLM call"

The invariant is:

- "committed translated transcript has no gaps relative to committed source transcript"

## Inputs

The engine consumes two kinds of input:

1. source transcript events
   - `p`: preview event
   - `c`: committed event
2. completed LLM results
   - result of a previously scheduled `preview` or `commit` request

This means the engine is not modeled as a single blocking `handle_event()` call anymore.

Instead it is conceptually:

- `ingest_source_event(...)`
- `ingest_llm_result(...)`

## Lanes

The engine has two logical lanes:

### Commit Lane

Properties:

- authoritative
- ordered
- must preserve contiguous committed coverage
- higher priority than preview

Commit lane work may be coalesced, but must not leave untranslated committed gaps.

### Preview Lane

Properties:

- best-effort
- lower priority than commit
- may skip work
- may drop stale work
- exists to improve snappiness, not correctness

Preview lane output must never corrupt or outrun committed target coverage.

## One Serialized Worker

The design assumes one serialized LLM worker/scheduler for now.

That means:

- only one LLM call runs at a time
- the engine may have multiple pending intents
- but dispatch remains serialized

This matches the current practical constraint that the LLM backend should not yet be treated as freely concurrent.

## Baseline Invariants

### 1. Commit Coverage Has No Gaps

Committed target text must cover committed source text contiguously and monotonically.

### 2. Commit Has Priority

If both commit and preview work are pending, commit dispatch wins.

### 3. Preview Is Compatibility-Based, Not Latest-Only

A finished preview result should be shown to the user unless it violates a hard compatibility rule.

The hard rule is:

- a preview result must not be applied if it was built on an older committed target base than the one currently visible

So preview display is:

- not strict `latest-wins`
- but `latest-compatible-wins`

In practice this means even an older preview result may still be useful to show if commit state has not advanced yet.

### 4. Unsent Preview Work Has No Guarantee

A preview event that could have triggered translation but has not yet been dispatched may be discarded.

The engine does not preserve a queue of pending preview requests.

It only preserves:

- the current preview intent
- the latest source state

If new committed input arrives before preview dispatch, preview is re-evaluated from the new state.

## State Model

The exact data model can still evolve, but the engine needs state in this shape:

- committed source state
- preview source state
- committed target state
- current visible preview target
- current committed target base revision
- whether commit work is needed
- whether preview work is needed
- whether an LLM request is in flight
- metadata for the in-flight request

The engine should also track enough metadata to know:

- which committed source span is already translated
- which committed source span still needs coverage
- which committed target base a preview result was built on

## Request Metadata

Each scheduled LLM request should carry metadata like:

- `lane`: `commit` or `preview`
- `committed_target_base_revision`
- source window or source span used
- dispatch-time source revision

Commit requests also need enough information to map the result back to the committed source coverage they are intended to fill.

## Scheduling Rule

When the worker becomes free:

1. if committed translation coverage is behind committed source coverage:
   - build and dispatch a commit request
2. else if preview is desired:
   - build and dispatch a preview request from the latest compatible state
3. else:
   - do nothing

Important:

- preview work should usually be kept as an intent, not materialized too early as a concrete request

Reason:

- while a commit request is running, newer `p` or `c` events may arrive
- so a prebuilt preview request can become stale before dispatch

## Result Application Rules

### Commit Result

When a commit result returns:

- apply it only if it still matches an untranslated committed source span
- advance committed translated coverage
- update committed target base revision
- invalidate incompatible preview state/results

### Preview Result

When a preview result returns:

- show it to the user if it is still compatible with the current committed target base
- otherwise discard it

A preview result does not advance committed coverage.

## Example Consequence

Scenario:

- `c1` -> request `a`
- `c2` arrives while `a` is running
- `p3`, `p4` arrive while `a` is running
- `a` finishes

Correct behavior:

- there is both commit work and preview intent
- dispatch next commit request first
- keep preview as an intent
- only build the next preview request after commit priority has been resolved

This avoids stale preview work while preserving committed correctness.

## Replay vs Live

Replay can still choose to run this engine in a simpler, more blocking way for experimentation.

Live usage must not require blocking source ingestion on LLM completion.

So the extracted engine should be designed for async event/result ingestion first.

Replay can then become a thin orchestration layer on top of that engine, rather than the engine defining the architecture.

## Current Design Decision Already Fixed

This note assumes the following explicit rule:

- every completed preview-lane result may be shown to the user
- unless doing so would violate committed-base compatibility

That rule is important for perceived snappiness.

## Open Questions

Still intentionally left open:

- exact source-span representation for commit coverage
- exact target stitching model for commit results
- whether requests should distinguish between:
  - context for understanding
  - untranslated span that must be covered
- whether preview and commit should share one translator prompt shape or diverge

Those are implementation questions on top of the state-machine basis defined here.

## Core vs Policy Boundary

The engine design depends on a hard separation between:

- the translation core
- the runner or dispatch policy

### Translation Core

The core is responsible for:

- ingesting all source transcript events
- maintaining source and target state
- enforcing commit and preview invariants
- determining whether the current state yields:
  - no translation opportunity
  - a preview opportunity
  - a commit opportunity
- applying completed LLM results back into state

The core is not responsible for:

- worker occupancy
- request serialization
- replay speed
- backpressure
- deciding whether an eligible opportunity is actually dispatched

In other words:

- eligibility is determined by the core
- dispatch is determined by policy

This means `p` and `c` events are always submitted to the core immediately.

The runner must not buffer raw transcript events outside the core and decide eligibility itself.

### Runner / Policy

The runner is responsible for:

- deciding whether an emitted opportunity is dispatched now, later, or not at all
- serializing LLM work
- blocking or non-blocking behavior
- handling pending intents while the worker is busy

So the core is policy-agnostic, while the runner is use-case-specific.

## Core Return Shape

The core should conceptually return a step result after each source event or LLM result.

That result should contain:

- state updates
- zero or one preview opportunity
- zero or one commit opportunity

The exact API shape is still open, but it should be rich enough that a runner can decide:

- continue immediately with the next source event
- dispatch an LLM request
- pause further event ingestion until a result returns

The core itself should not know whether the caller is replay or live.

## Replay Policy

Replay exists to evaluate translation quality of prompt/model combinations, not to simulate live backpressure.

That means replay should remain eager.

Replay policy rules:

1. submit each source event to the core immediately
2. if the core returns no opportunity:
   - continue with the next source event
3. if the core returns a preview or commit opportunity:
   - dispatch it immediately
   - pause further source-event ingestion
   - wait for the corresponding LLM result
   - submit that result back to the core
   - only then continue with the next source event

So replay is effectively:

- event-by-event
- eager
- blocking whenever an LLM call is actually launched

This preserves the current evaluation behavior:

- many relevant translation opportunities are exercised
- `fast` and `fastest` remain useful for judging prompt/model quality

Replay must not inherit live-style preview dropping or aggressive coalescing, because that would make prompt/model evaluation uninformative.

## Live Policy

Live use is operational, not evaluative.

That means live policy must keep transcript ingestion responsive and avoid blocking on LLM completion.

Live policy rules:

1. submit every source event to the core immediately
2. if the core emits commit and/or preview opportunities:
   - record them as pending intents
3. if the worker is busy:
   - do not block transcript ingestion
4. when the worker becomes free:
   - dispatch commit work first if committed coverage is behind
   - otherwise dispatch preview work if preview is still desired

Important:

- preview work should usually be preserved as an intent, not immediately frozen as a concrete request while another request is still running

Reason:

- more `p` or `c` events may arrive before dispatch
- so the concrete preview request should be built from the newest state when the worker actually becomes free

### Preview Dropping in Live

Unsent preview work has no delivery guarantee.

If a preview opportunity could have been sent but was not yet dispatched, and new source state arrives before dispatch, that old preview opportunity may be discarded.

More precisely:

- the live runner does not maintain a queue of old preview opportunities
- it only maintains the latest preview intent derived from current core state

If new committed source arrives before preview dispatch, preview is re-evaluated after commit priority is handled.

## Example Difference Between Policies

Suppose the core sees a sequence where a preview opportunity appears.

Replay policy:

- dispatches it immediately
- blocks further source ingestion until the result returns

Live policy:

- may keep it only as a pending preview intent
- may let later source events supersede it
- may delay dispatch until commit work is cleared

This difference is intentional.

Replay measures translation quality.
Live manages operational responsiveness.
