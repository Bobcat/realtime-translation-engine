from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from realtime_translation_engine.translators import build_translator
from realtime_translation_engine.translators import DummyTranslator
from realtime_translation_engine.translators import LlmResponsesTranslator


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object], *, status: int = 200, reason: str = "OK") -> None:
        self.status = status
        self.reason = reason
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body


class FakeHttpConnection:
    def __init__(self, responses: list[FakeHttpResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def request(self, method: str, target: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        self.requests.append(
            {
                "method": method,
                "target": target,
                "body": body,
                "headers": headers or {},
            }
        )

    def getresponse(self) -> FakeHttpResponse:
        if not self.responses:
            raise AssertionError("No fake HTTP responses queued")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def make_json_response(
    *,
    response_id: str,
    model: str,
    output_text: str,
    metrics: dict[str, object] | None = None,
) -> FakeHttpResponse:
    return FakeHttpResponse(
        {
            "id": response_id,
            "object": "response",
            "model": model,
            "output": [{"type": "output_text", "text": output_text}],
            "output_text": output_text,
            "metrics": metrics or {},
        }
    )


def make_connection(*responses: FakeHttpResponse) -> FakeHttpConnection:
    return FakeHttpConnection(list(responses))


def decode_request_payload(connection: FakeHttpConnection, index: int = 0) -> dict[str, object]:
    return json.loads(connection.requests[index]["body"].decode("utf-8"))


def patch_http_connection(connection: FakeHttpConnection):
    return patch(
        "realtime_translation_engine.translators.llmpool.http.client.HTTPConnection",
        return_value=connection,
    )


class BuildTranslatorTests(unittest.TestCase):
    def test_build_translator_dummy_returns_dummy_translator(self) -> None:
        translator = build_translator("dummy", dummy_mode="echo")
        self.assertIsInstance(translator, DummyTranslator)
        self.assertEqual(translator.mode, "echo")

    def test_build_translator_llm_responses_uses_llm_responses_translator(self) -> None:
        marker = object()
        with patch("realtime_translation_engine.translators.LlmResponsesTranslator", return_value=marker):
            translator = build_translator("llm-responses")
        self.assertIs(translator, marker)

    def test_build_translator_llm_responses_passes_service_second_pass_and_templates(self) -> None:
        marker = object()
        with patch("realtime_translation_engine.translators.LlmResponsesTranslator", return_value=marker) as ctor:
            translator = build_translator(
                "llm-responses",
                service_model="qwen2.5-14b-instruct-ct2-int8",
                second_pass_model="phi-4-ct2-int8",
                first_pass_prompt="Translate to Dutch only.",
                first_pass_input_template="INPUT={{source_window}}",
                second_pass_input_template="SRC={{source_window}} D={{draft_translation}}",
                source_language="English",
                target_language="Dutch",
            )
        self.assertIs(translator, marker)
        ctor.assert_called_once_with(
            model="qwen2.5-14b-instruct-ct2-int8",
            second_pass_model="phi-4-ct2-int8",
            first_pass_prompt="Translate to Dutch only.",
            first_pass_input_template="INPUT={{source_window}}",
            second_pass_input_template="SRC={{source_window}} D={{draft_translation}}",
            source_language="English",
            target_language="Dutch",
        )

    def test_build_translator_rejects_unknown_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported translator"):
            build_translator("unknown-backend")

    def test_translate_posts_to_llm_responses_api(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_1",
                model="eurollm-9b-ct2-int8",
                output_text="Hallo wereld",
                metrics={
                    "engine_queue_wait_ms": 3.5,
                    "backend_inference_wall_ms": 20.0,
                    "engine_total_wall_ms": 24.0,
                    "engine_outside_backend_wall_ms": 4.0,
                    "pool_total_wall_ms": 25.0,
                    "gpu_generate_total_ms": 12.5,
                    "engine_output_tokens": 2,
                },
            )
        )
        with patch_http_connection(connection) as mock_http:
            result = translator.translate("Hello world")

        self.assertEqual(result.text, "Hallo wereld")
        self.assertEqual(result.request_id, "resp_1")
        self.assertEqual(result.model, "eurollm-9b-ct2-int8")
        self.assertEqual(result.metrics.engine_output_tokens, 2)
        self.assertEqual(result.metrics.engine_queue_wait_ms, 3.5)
        self.assertEqual(result.metrics.backend_inference_wall_ms, 20.0)
        self.assertEqual(result.metrics.engine_total_wall_ms, 24.0)
        self.assertEqual(result.metrics.engine_outside_backend_wall_ms, 4.0)
        self.assertEqual(result.metrics.pool_total_wall_ms, 25.0)
        self.assertEqual(result.metrics.gpu_generate_total_ms, 12.5)
        self.assertEqual(mock_http.call_count, 1)
        self.assertEqual(connection.requests[0]["target"], "/v1/responses")
        self.assertEqual(connection.requests[0]["headers"]["Accept"], "application/json")
        payload = decode_request_payload(connection)
        self.assertEqual(payload["model"], "eurollm-9b-ct2-int8")
        self.assertEqual(payload["input"], "Hello world")
        self.assertEqual(
            payload["instructions"],
            "You are a translation engine. Translate the user's text into Dutch. Return only the translation.",
        )
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["decoding"]["beam_size"], 1)
        self.assertEqual(payload["decoding"]["top_k"], 1)
        self.assertEqual(payload["decoding"]["temperature"], 0.1)

    def test_translate_uses_configured_first_pass_prompt(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
            first_pass_prompt="Translate from {{source_lang}} to {{target_lang}} only. Return only the translation.",
            source_language="English",
            target_language="Dutch",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_1b",
                model="eurollm-9b-ct2-int8",
                output_text="Hallo",
            )
        )
        with patch_http_connection(connection):
            translator.translate("Hello")

        payload = decode_request_payload(connection)
        self.assertEqual(
            payload["instructions"],
            "Translate from English to Dutch only. Return only the translation.",
        )

    def test_translate_uses_first_pass_input_template(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
            first_pass_input_template="INPUT={{source_lang}}>{{target_lang}}:{{source_window}}",
            source_language="English",
            target_language="Dutch",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_tpl_1",
                model="eurollm-9b-ct2-int8",
                output_text="ok",
            )
        )
        with patch_http_connection(connection):
            translator.translate("Hello world")

        payload = decode_request_payload(connection)
        self.assertEqual(payload["input"], "INPUT=English>Dutch:Hello world")

    def test_translate_with_system_prompt_posts_custom_decoding_params(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
            max_length=512,
            sampling_topk=1,
            sampling_temperature=0.1,
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_2",
                model="eurollm-9b-ct2-int8",
                output_text="Aangepaste vertaling",
            )
        )
        with patch_http_connection(connection):
            result = translator.translate_with_system_prompt(
                "Hello world",
                system_prompt="Custom system prompt",
                beam_size=3,
                sampling_topk=5,
                sampling_temperature=0.3,
            )

        self.assertEqual(result.text, "Aangepaste vertaling")
        payload = decode_request_payload(connection)
        self.assertEqual(payload["instructions"], "Custom system prompt")
        self.assertEqual(payload["decoding"]["beam_size"], 3)
        self.assertEqual(payload["decoding"]["top_k"], 5)
        self.assertEqual(payload["decoding"]["temperature"], 0.3)
        self.assertEqual(payload["decoding"]["max_tokens"], 512)

    def test_translate_reads_json_output_text(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_3",
                model="eurollm-9b-ct2-int8",
                output_text="Hallo wereld",
            )
        )
        with patch_http_connection(connection):
            result = translator.translate("Hello world")

        self.assertEqual(result.text, "Hallo wereld")

    def test_run_second_pass_posts_source_and_draft_to_second_pass_model(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="phi-4-ct2-int8",
            second_pass_model="eurollm-9b-ct2-int8",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_4",
                model="eurollm-9b-ct2-int8",
                output_text="Hallo wereld",
            )
        )
        with patch_http_connection(connection):
            result = translator.run_second_pass("Hello world", "Hoi wereld")

        self.assertEqual(result.text, "Hallo wereld")
        payload = decode_request_payload(connection)
        self.assertEqual(payload["model"], "eurollm-9b-ct2-int8")
        self.assertEqual(
            payload["input"],
            "Source text:\nHello world\n\nDraft Dutch translation:\nHoi wereld",
        )
        self.assertIn("You are the second pass of a translation pipeline", payload["instructions"])
        self.assertIn("Return only the final Dutch translation.", payload["instructions"])

    def test_run_second_pass_uses_second_pass_input_template(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="phi-4-ct2-int8",
            second_pass_model="eurollm-9b-ct2-int8",
            second_pass_input_template="SRC={{source_window}}\nDRAFT={{draft_translation}}",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_tpl_2",
                model="eurollm-9b-ct2-int8",
                output_text="ok",
            )
        )
        with patch_http_connection(connection):
            translator.run_second_pass("SRC", "DRAFT")

        payload = decode_request_payload(connection)
        self.assertEqual(payload["input"], "SRC=SRC\nDRAFT=DRAFT")

    def test_run_second_pass_runs_second_call_when_second_pass_model_matches_first_pass(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
            second_pass_model="eurollm-9b-ct2-int8",
        )

        connection = make_connection(
            make_json_response(
                response_id="resp_5",
                model="eurollm-9b-ct2-int8",
                output_text="Verbeterde vertaling",
            )
        )
        with patch_http_connection(connection) as mock_http:
            result = translator.run_second_pass("Hello world", "Hallo wereld")

        self.assertEqual(result.text, "Verbeterde vertaling")
        self.assertEqual(result.model, "eurollm-9b-ct2-int8")
        mock_http.assert_called_once()

    def test_translate_reuses_http_connection_across_calls(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
        )
        connection = make_connection(
            make_json_response(
                response_id="resp_reuse_1",
                model="eurollm-9b-ct2-int8",
                output_text="een",
            ),
            make_json_response(
                response_id="resp_reuse_2",
                model="eurollm-9b-ct2-int8",
                output_text="twee",
            ),
        )

        with patch_http_connection(connection) as mock_http:
            first = translator.translate("one")
            second = translator.translate("two")

        self.assertEqual(first.text, "een")
        self.assertEqual(second.text, "twee")
        self.assertEqual(mock_http.call_count, 1)
        self.assertEqual(len(connection.requests), 2)


if __name__ == "__main__":
    unittest.main()
