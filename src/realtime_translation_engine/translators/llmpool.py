from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import http.client
import json
import os
import time
from urllib.parse import SplitResult
from urllib.parse import urlsplit

from ..translator import TranslationMetrics
from ..translator import TranslationResult

DEFAULT_TARGET_LANGUAGE = "Dutch"
DEFAULT_SOURCE_LANGUAGE = "English"
DEFAULT_LLM_RESPONSES_API_MODEL = os.environ.get("LLM_RESPONSES_API_MODEL", "eurollm-9b-ct2-int8")
DEFAULT_LLM_RESPONSES_API_SECOND_PASS_MODEL = os.environ.get(
    "LLM_RESPONSES_API_SECOND_PASS_MODEL",
    "phi-4-ct2-int8",
)
DEFAULT_LLM_RESPONSES_API_BASE_URL = os.environ.get("LLM_RESPONSES_API_BASE_URL", "http://127.0.0.1:8011")


@dataclass
class LlmResponsesTranslator:
    service_base_url: str = DEFAULT_LLM_RESPONSES_API_BASE_URL
    model: str = DEFAULT_LLM_RESPONSES_API_MODEL
    second_pass_model: str = DEFAULT_LLM_RESPONSES_API_SECOND_PASS_MODEL
    first_pass_prompt: str | None = None
    first_pass_input_template: str = "{{source_window}}"
    first_pass_inline_user_prompt: bool = False
    second_pass_inline_user_prompt: bool = False
    second_pass_input_template: str = (
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
    _connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _second_pass_translator: LlmResponsesTranslator | None = field(default=None, init=False, repr=False)

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

    def run_second_pass(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> TranslationResult:
        if draft_translation.strip() == "":
            return TranslationResult(text=draft_translation, model=self.model)
        second_pass_model = self.second_pass_model.strip()
        if second_pass_model == "":
            return TranslationResult(text=draft_translation, model=self.model)
        second_pass_prompt = system_prompt if system_prompt is not None else self._second_pass_system_prompt()
        second_pass_input = render_translation_template(
            self.second_pass_input_template,
            source_window=source_window,
            draft_translation=draft_translation,
            source_language=self.source_language,
            target_language=self.target_language,
        )
        if second_pass_input.strip() == "":
            second_pass_input = draft_translation
        second_pass_translator = self if second_pass_model == self.model else self._get_second_pass_translator()
        if self.second_pass_inline_user_prompt:
            inline_input = self._build_second_pass_inline_user_prompt(
                prompt=second_pass_prompt,
                source_window=source_window,
                draft_translation=draft_translation,
            )
            return second_pass_translator.translate_with_system_prompt(
                inline_input,
                system_prompt=" ",
            )
        return second_pass_translator.translate_with_system_prompt(
            second_pass_input,
            system_prompt=second_pass_prompt,
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
            "stream": False,
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

    def _second_pass_system_prompt(self) -> str:
        return (
            "You are the second pass of a translation pipeline for Dutch output. "
            "You receive source text and a draft Dutch translation. "
            "Produce clean, idiomatic Dutch and correct clear language errors in the draft. "
            "If the draft contains malformed or non-Dutch words, replace them with the most likely correct Dutch wording. "
            "Fix obvious mistranscription effects from the source when the intended meaning is clear. "
            "Preserve meaning and factual content; do not add new information. "
            "If genuinely ambiguous, choose the safest natural Dutch wording closest to the source intent. "
            "Return only the final Dutch translation."
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

    def _build_second_pass_inline_user_prompt(
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
        request_started = time.perf_counter()
        try:
            return self._execute_request(body, request_started=request_started, retry_stale_connection=True)
        except OSError as exc:
            self._close_connection()
            raise RuntimeError(f"llm-responses API unavailable: {exc}") from exc

    def _execute_request(
        self,
        body: bytes,
        *,
        request_started: float,
        retry_stale_connection: bool,
    ) -> TranslationResult:
        try:
            connection = self._get_connection()
            connection.request(
                "POST",
                self._responses_path(),
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            transport_first_byte_ms = (time.perf_counter() - request_started) * 1000.0
            raw_body = response.read()
        except (
            BrokenPipeError,
            ConnectionResetError,
            http.client.BadStatusLine,
            http.client.CannotSendRequest,
            http.client.RemoteDisconnected,
            http.client.ResponseNotReady,
        ) as exc:
            self._close_connection()
            if retry_stale_connection:
                return self._execute_request(
                    body,
                    request_started=request_started,
                    retry_stale_connection=False,
                )
            raise RuntimeError(f"llm-responses API unavailable: {exc}") from exc

        if response.status >= 400:
            detail = raw_body.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"llm-responses API HTTP {response.status}: {detail.strip() or response.reason}"
            )

        return self._read_json_response(
            raw_body,
            request_started=request_started,
            transport_first_byte_ms=transport_first_byte_ms,
        )

    def _read_json_response(
        self,
        raw_body: bytes,
        *,
        request_started: float,
        transport_first_byte_ms: float,
    ) -> TranslationResult:
        payload = json.loads(raw_body.decode("utf-8"))
        transport_completed_ms = (time.perf_counter() - request_started) * 1000.0
        metrics_payload = payload.get("metrics", {})
        if not isinstance(metrics_payload, dict):
            metrics_payload = {}
        return TranslationResult(
            text=str(payload.get("output_text", "")).strip(),
            request_id=str(payload.get("id", "")),
            model=str(payload.get("model", self.model)),
            metrics=self._build_metrics(
                transport_first_byte_ms=transport_first_byte_ms,
                transport_first_text_delta_ms=transport_completed_ms,
                transport_completed_ms=transport_completed_ms,
                response_metrics_payload=metrics_payload,
            ),
        )

    def _service_base_parts(self) -> SplitResult:
        parts = urlsplit(self.service_base_url.rstrip("/"))
        if parts.scheme not in {"http", "https"}:
            raise ValueError(f"unsupported llm-responses base URL scheme: {parts.scheme!r}")
        if not parts.hostname:
            raise ValueError(f"invalid llm-responses base URL: {self.service_base_url!r}")
        return parts

    def _responses_path(self) -> str:
        parts = self._service_base_parts()
        base_path = parts.path.rstrip("/")
        if base_path:
            return f"{base_path}/v1/responses"
        return "/v1/responses"

    def _get_connection(self) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        if self._connection is not None:
            return self._connection
        parts = self._service_base_parts()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if parts.scheme == "https":
            self._connection = http.client.HTTPSConnection(parts.hostname, port, timeout=self.timeout_seconds)
        else:
            self._connection = http.client.HTTPConnection(parts.hostname, port, timeout=self.timeout_seconds)
        return self._connection

    def _close_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None

    def _get_second_pass_translator(self) -> LlmResponsesTranslator:
        second_pass_model = self.second_pass_model.strip()
        translator = self._second_pass_translator
        if translator is not None and translator.model == second_pass_model:
            return translator
        translator = LlmResponsesTranslator(
            service_base_url=self.service_base_url,
            model=second_pass_model,
            second_pass_model=second_pass_model,
            first_pass_input_template=self.first_pass_input_template,
            first_pass_inline_user_prompt=self.first_pass_inline_user_prompt,
            second_pass_inline_user_prompt=self.second_pass_inline_user_prompt,
            second_pass_input_template=self.second_pass_input_template,
            source_language=self.source_language,
            target_language=self.target_language,
            max_length=self.max_length,
            sampling_topk=self.sampling_topk,
            sampling_topp=self.sampling_topp,
            sampling_temperature=self.sampling_temperature,
            repetition_penalty=self.repetition_penalty,
            timeout_seconds=self.timeout_seconds,
        )
        self._second_pass_translator = translator
        return translator

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
            engine_queue_wait_ms=_maybe_float(response_metrics_payload.get("engine_queue_wait_ms")),
            backend_inference_wall_ms=_maybe_float(response_metrics_payload.get("backend_inference_wall_ms")),
            engine_total_wall_ms=_maybe_float(response_metrics_payload.get("engine_total_wall_ms")),
            engine_outside_backend_wall_ms=_maybe_float(response_metrics_payload.get("engine_outside_backend_wall_ms")),
            pool_total_wall_ms=_maybe_float(response_metrics_payload.get("pool_total_wall_ms")),
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
