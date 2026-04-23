from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from urllib import error
from urllib import request

from ..translator import TranslationMetrics
from ..translator import TranslationResult

DEFAULT_TARGET_LANGUAGE = "Dutch"
DEFAULT_SOURCE_LANGUAGE = "English"
DEFAULT_LLM_RESPONSES_API_MODEL = os.environ.get("LLM_RESPONSES_API_MODEL", "eurollm-9b-ct2-int8")
DEFAULT_LLM_RESPONSES_API_CORRECTION_MODEL = os.environ.get(
    "LLM_RESPONSES_API_CORRECTION_MODEL",
    "phi-4-ct2-int8",
)
DEFAULT_LLM_RESPONSES_API_BASE_URL = os.environ.get("LLM_RESPONSES_API_BASE_URL", "http://127.0.0.1:8011")


@dataclass
class LlmResponsesTranslator:
    service_base_url: str = DEFAULT_LLM_RESPONSES_API_BASE_URL
    model: str = DEFAULT_LLM_RESPONSES_API_MODEL
    correction_model: str = DEFAULT_LLM_RESPONSES_API_CORRECTION_MODEL
    first_pass_prompt: str | None = None
    first_pass_input_template: str = "{{source_window}}"
    first_pass_inline_user_prompt: bool = False
    correction_inline_user_prompt: bool = False
    correction_input_template: str = (
        "Source text:\n"
        "{{source_window}}\n\n"
        "Draft Dutch translation:\n"
        "{{draft_translation}}"
    )
    source_language: str = DEFAULT_SOURCE_LANGUAGE
    target_language: str = DEFAULT_TARGET_LANGUAGE
    max_length: int = 256
    sampling_topk: int = 1
    sampling_topp: float = 1.0
    sampling_temperature: float = 0.1
    repetition_penalty: float = 1.0
    timeout_seconds: float = 120.0

    def translate(self, source_window: str) -> TranslationResult:
        first_pass_prompt = (self.first_pass_prompt or "").strip()
        if first_pass_prompt == "":
            first_pass_prompt = self._default_system_prompt()
        else:
            first_pass_prompt = render_translation_template(
                first_pass_prompt,
                source_window=source_window,
                source_language=self.source_language,
                target_language=self.target_language,
            )
        if self.first_pass_inline_user_prompt:
            if source_window.strip() == "":
                return TranslationResult(text="", model=self.model)
            request_input = self._build_first_pass_inline_user_prompt(
                prompt=first_pass_prompt,
                source_window=source_window,
            )
            return self.translate_with_system_prompt(
                request_input,
                system_prompt=" ",
            )
        request_input = render_translation_template(
            self.first_pass_input_template,
            source_window=source_window,
            source_language=self.source_language,
            target_language=self.target_language,
        )
        if request_input.strip() == "":
            request_input = source_window
        return self.translate_with_system_prompt(
            request_input,
            system_prompt=first_pass_prompt,
        )

    def revise_translation(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> TranslationResult:
        if draft_translation.strip() == "":
            return TranslationResult(text=draft_translation, model=self.model)
        correction_model = self.correction_model.strip()
        if correction_model == "":
            return TranslationResult(text=draft_translation, model=self.model)
        revision_prompt = system_prompt if system_prompt is not None else self._revision_system_prompt()
        correction_input = render_translation_template(
            self.correction_input_template,
            source_window=source_window,
            draft_translation=draft_translation,
            source_language=self.source_language,
            target_language=self.target_language,
        )
        if correction_input.strip() == "":
            correction_input = draft_translation
        correction_translator = LlmResponsesTranslator(
            service_base_url=self.service_base_url,
            model=correction_model,
            correction_model=correction_model,
            first_pass_input_template=self.first_pass_input_template,
            first_pass_inline_user_prompt=self.first_pass_inline_user_prompt,
            correction_inline_user_prompt=self.correction_inline_user_prompt,
            correction_input_template=self.correction_input_template,
            source_language=self.source_language,
            target_language=self.target_language,
            max_length=self.max_length,
            sampling_topk=self.sampling_topk,
            sampling_topp=self.sampling_topp,
            sampling_temperature=self.sampling_temperature,
            repetition_penalty=self.repetition_penalty,
            timeout_seconds=self.timeout_seconds,
        )
        if self.correction_inline_user_prompt:
            inline_input = self._build_revision_inline_user_prompt(
                prompt=revision_prompt,
                source_window=source_window,
                draft_translation=draft_translation,
            )
            return correction_translator.translate_with_system_prompt(
                inline_input,
                system_prompt=" ",
            )
        return correction_translator.translate_with_system_prompt(
            correction_input,
            system_prompt=revision_prompt,
        )

    def translate_with_system_prompt(
        self,
        source_window: str,
        *,
        system_prompt: str,
        beam_size: int = 1,
        sampling_topk: int | None = None,
        sampling_temperature: float | None = None,
    ) -> TranslationResult:
        if source_window.strip() == "":
            return TranslationResult(text="", model=self.model)
        payload = {
            "model": self.model,
            "input": source_window,
            "instructions": system_prompt,
            "stream": True,
            "decoding": {
                "beam_size": beam_size,
                "top_k": self.sampling_topk if sampling_topk is None else sampling_topk,
                "top_p": self.sampling_topp,
                "temperature": self.sampling_temperature if sampling_temperature is None else sampling_temperature,
                "repetition_penalty": self.repetition_penalty,
                "max_tokens": self.max_length,
                "stop": ["<|im_end|>"],
            },
        }
        return self._submit_request(payload)

    def _default_system_prompt(self) -> str:
        return (
            "You are a translation engine. "
            f"Translate the user's text into {self.target_language}. "
            "Return only the translation."
        )

    def _revision_system_prompt(self) -> str:
        return (
            "You are correcting a Dutch translation. "
            "You receive source text and a draft Dutch translation. "
            "Produce clean, idiomatic Dutch and correct clear language errors in the draft. "
            "If the draft contains malformed or non-Dutch words, replace them with the most likely correct Dutch wording. "
            "Fix obvious mistranscription effects from the source when the intended meaning is clear. "
            "Preserve meaning and factual content; do not add new information. "
            "If genuinely ambiguous, choose the safest natural Dutch wording closest to the source intent. "
            "Return only the final corrected Dutch translation."
        )

    def _build_first_pass_inline_user_prompt(self, *, prompt: str, source_window: str) -> str:
        instruction_text = str(prompt or "").rstrip("\n")
        source_text = str(source_window or "").rstrip("\n")
        return (
            f"{instruction_text}\n"
            f"ATTACHMENTS:\n"
            f"Name: source.txt\n"
            f"Contents:\n"
            f"=====\n"
            f"{source_text}\n"
            f"=====\n"
        )

    def _build_revision_inline_user_prompt(
        self,
        *,
        prompt: str,
        source_window: str,
        draft_translation: str,
    ) -> str:
        instruction_text = str(prompt or "").rstrip("\n")
        source_text = str(source_window or "").rstrip("\n")
        draft_text = str(draft_translation or "").rstrip("\n")
        return (
            f"{instruction_text}\n"
            f"ATTACHMENTS:\n"
            f"Name: source.txt\n"
            f"Contents:\n"
            f"=====\n"
            f"{source_text}\n"
            f"=====\n"
            f"Name: draft_translation.txt\n"
            f"Contents:\n"
            f"=====\n"
            f"{draft_text}\n"
            f"=====\n"
        )

    def _submit_request(self, payload: dict[str, object]) -> TranslationResult:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req = request.Request(
            url=f"{self.service_base_url.rstrip('/')}/v1/responses",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        request_started = time.perf_counter()
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                transport_first_byte_ms = (time.perf_counter() - request_started) * 1000.0
                return self._read_sse_response(
                    response,
                    request_started=request_started,
                    transport_first_byte_ms=transport_first_byte_ms,
                )
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"llm-responses API HTTP {exc.code}: {detail.strip() or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"llm-responses API unavailable: {exc.reason}") from exc

    def _read_sse_response(
        self,
        response: object,
        *,
        request_started: float,
        transport_first_byte_ms: float,
    ) -> TranslationResult:
        deltas: list[str] = []
        event_name = ""
        data_lines: list[str] = []
        request_id = ""
        response_model = self.model
        response_metrics_payload: dict[str, object] = {}
        transport_first_text_delta_ms: float | None = None

        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line == "":
                completed_result = self._handle_sse_event(
                    event_name,
                    data_lines,
                    deltas,
                    request_started=request_started,
                    request_id=request_id,
                    response_model=response_model,
                    transport_first_byte_ms=transport_first_byte_ms,
                    transport_first_text_delta_ms=transport_first_text_delta_ms,
                    response_metrics_payload=response_metrics_payload,
                )
                if completed_result is not None:
                    return completed_result
                if event_name == "response.created" and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    request_id = str(payload.get("id", request_id))
                    response_model = str(payload.get("model", response_model))
                elif event_name == "response.output_text.delta" and data_lines and transport_first_text_delta_ms is None:
                    transport_first_text_delta_ms = (time.perf_counter() - request_started) * 1000.0
                elif event_name == "response.metrics" and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    metrics_payload = payload.get("metrics", {})
                    if isinstance(metrics_payload, dict):
                        response_metrics_payload = dict(metrics_payload)
                event_name = ""
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
                continue
            if line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())

        completed_result = self._handle_sse_event(
            event_name,
            data_lines,
            deltas,
            request_started=request_started,
            request_id=request_id,
            response_model=response_model,
            transport_first_byte_ms=transport_first_byte_ms,
            transport_first_text_delta_ms=transport_first_text_delta_ms,
            response_metrics_payload=response_metrics_payload,
        )
        if completed_result is not None:
            return completed_result
        return TranslationResult(
            text="".join(deltas).strip(),
            request_id=request_id,
            model=response_model,
            metrics=self._build_metrics(
                transport_first_byte_ms=transport_first_byte_ms,
                transport_first_text_delta_ms=transport_first_text_delta_ms,
                transport_completed_ms=(time.perf_counter() - request_started) * 1000.0,
                response_metrics_payload=response_metrics_payload,
            ),
        )

    def _handle_sse_event(
        self,
        event_name: str,
        data_lines: list[str],
        deltas: list[str],
        *,
        request_started: float,
        request_id: str,
        response_model: str,
        transport_first_byte_ms: float,
        transport_first_text_delta_ms: float | None,
        response_metrics_payload: dict[str, object],
    ) -> TranslationResult | None:
        if not event_name or not data_lines:
            return None
        payload = json.loads("\n".join(data_lines))
        if event_name == "response.output_text.delta":
            deltas.append(str(payload.get("delta", "")))
            return None
        if event_name == "response.completed":
            output_text = str(payload.get("output_text", ""))
            return TranslationResult(
                text=output_text.strip() if output_text else "".join(deltas).strip(),
                request_id=str(payload.get("id", request_id)),
                model=response_model,
                metrics=self._build_metrics(
                    transport_first_byte_ms=transport_first_byte_ms,
                    transport_first_text_delta_ms=transport_first_text_delta_ms,
                    transport_completed_ms=(time.perf_counter() - request_started) * 1000.0,
                    response_metrics_payload=response_metrics_payload,
                ),
            )
        return None

    def _build_metrics(
        self,
        *,
        transport_first_byte_ms: float | None,
        transport_first_text_delta_ms: float | None,
        transport_completed_ms: float | None,
        response_metrics_payload: dict[str, object],
    ) -> TranslationMetrics:
        return TranslationMetrics(
            transport_first_byte_ms=transport_first_byte_ms,
            transport_first_text_delta_ms=transport_first_text_delta_ms,
            transport_completed_ms=transport_completed_ms,
            engine_tokenize_ms=_maybe_float(response_metrics_payload.get("engine_tokenize_ms")),
            gpu_time_to_first_token_ms=_maybe_float(response_metrics_payload.get("gpu_time_to_first_token_ms")),
            gpu_generate_total_ms=_maybe_float(response_metrics_payload.get("gpu_generate_total_ms")),
            gpu_decode_after_first_token_ms=_maybe_float(response_metrics_payload.get("gpu_decode_after_first_token_ms")),
            engine_prompt_tokens=_maybe_int(response_metrics_payload.get("engine_prompt_tokens")),
            engine_output_tokens=_maybe_int(response_metrics_payload.get("engine_output_tokens")),
            engine_tokens_per_second=_maybe_float(response_metrics_payload.get("engine_tokens_per_second")),
        )


def render_translation_template(template: str, **variables: str) -> str:
    rendered = str(template)
    known_variables = {
        "source_window": str(variables.get("source_window", "")),
        "source_lang": str(variables.get("source_language", "")),
        "target_lang": str(variables.get("target_language", "")),
        "draft_translation": str(variables.get("draft_translation", "")),
    }
    for name, value in known_variables.items():
        rendered = rendered.replace(f"{{{{{name}}}}}", value)
    return rendered


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _maybe_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
