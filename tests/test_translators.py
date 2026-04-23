from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from realtime_translation_engine.translators import build_translator
from realtime_translation_engine.translators import DummyTranslator
from realtime_translation_engine.translators import LlmResponsesTranslator


class FakeHttpResponse:
    def __init__(self, text: str) -> None:
        self._lines = [line.encode("utf-8") for line in text.splitlines(keepends=True)]

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


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

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_1","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_1","delta":"Hallo "}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_1","delta":"wereld"}\n\n'
                "event: response.metrics\n"
                'data: {"id":"resp_1","metrics":{"gpu_generate_total_ms":12.5,"engine_output_tokens":2}}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_1","output_text":"Hallo wereld"}\n\n'
            ),
        ) as mock_urlopen:
            result = translator.translate("Hello world")

        self.assertEqual(result.text, "Hallo wereld")
        self.assertEqual(result.request_id, "resp_1")
        self.assertEqual(result.model, "eurollm-9b-ct2-int8")
        self.assertEqual(result.metrics.engine_output_tokens, 2)
        self.assertEqual(result.metrics.gpu_generate_total_ms, 12.5)
        request_obj = mock_urlopen.call_args.args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(payload["model"], "eurollm-9b-ct2-int8")
        self.assertEqual(payload["input"], "Hello world")
        self.assertEqual(
            payload["instructions"],
            "You are a translation engine. Translate the user's text into Dutch. Return only the translation.",
        )
        self.assertTrue(payload["stream"])
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

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_1b","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_1b","delta":"Hallo"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_1b","output_text":"Hallo"}\n\n'
            ),
        ) as mock_urlopen:
            translator.translate("Hello")

        request_obj = mock_urlopen.call_args.args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
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

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_tpl_1","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_tpl_1","output_text":"ok"}\n\n'
            ),
        ) as mock_urlopen:
            translator.translate("Hello world")

        request_obj = mock_urlopen.call_args.args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(payload["input"], "INPUT=English>Dutch:Hello world")

    def test_translate_with_system_prompt_posts_custom_decoding_params(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
            max_length=512,
            sampling_topk=1,
            sampling_temperature=0.1,
        )

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_2","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_2","delta":"Aangepaste "}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_2","delta":"vertaling"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_2","output_text":"Aangepaste vertaling"}\n\n'
            ),
        ) as mock_urlopen:
            result = translator.translate_with_system_prompt(
                "Hello world",
                system_prompt="Custom system prompt",
                beam_size=3,
                sampling_topk=5,
                sampling_temperature=0.3,
            )

        self.assertEqual(result.text, "Aangepaste vertaling")
        request_obj = mock_urlopen.call_args.args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(payload["instructions"], "Custom system prompt")
        self.assertEqual(payload["decoding"]["beam_size"], 3)
        self.assertEqual(payload["decoding"]["top_k"], 5)
        self.assertEqual(payload["decoding"]["temperature"], 0.3)
        self.assertEqual(payload["decoding"]["max_tokens"], 512)

    def test_translate_falls_back_to_accumulated_deltas_when_completed_has_no_text(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
        )

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_3","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_3","delta":"Hallo"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_3","delta":" wereld"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_3"}\n\n'
            ),
        ):
            result = translator.translate("Hello world")

        self.assertEqual(result.text, "Hallo wereld")

    def test_run_second_pass_posts_source_and_draft_to_second_pass_model(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="phi-4-ct2-int8",
            second_pass_model="eurollm-9b-ct2-int8",
        )

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_4","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_4","delta":"Hallo wereld"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_4","output_text":"Hallo wereld"}\n\n'
            ),
        ) as mock_urlopen:
            result = translator.run_second_pass("Hello world", "Hoi wereld")

        self.assertEqual(result.text, "Hallo wereld")
        request_obj = mock_urlopen.call_args.args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
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

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_tpl_2","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_tpl_2","output_text":"ok"}\n\n'
            ),
        ) as mock_urlopen:
            translator.run_second_pass("SRC", "DRAFT")

        request_obj = mock_urlopen.call_args.args[0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        self.assertEqual(payload["input"], "SRC=SRC\nDRAFT=DRAFT")

    def test_run_second_pass_runs_second_call_when_second_pass_model_matches_first_pass(self) -> None:
        translator = LlmResponsesTranslator(
            service_base_url="http://127.0.0.1:8010",
            model="eurollm-9b-ct2-int8",
            second_pass_model="eurollm-9b-ct2-int8",
        )

        with patch(
            "realtime_translation_engine.translators.llmpool.request.urlopen",
            return_value=FakeHttpResponse(
                "event: response.created\n"
                'data: {"id":"resp_5","model":"eurollm-9b-ct2-int8","object":"response"}\n\n'
                "event: response.output_text.delta\n"
                'data: {"id":"resp_5","delta":"Verbeterde vertaling"}\n\n'
                "event: response.completed\n"
                'data: {"id":"resp_5","output_text":"Verbeterde vertaling"}\n\n'
            ),
        ) as mock_urlopen:
            result = translator.run_second_pass("Hello world", "Hallo wereld")

        self.assertEqual(result.text, "Verbeterde vertaling")
        self.assertEqual(result.model, "eurollm-9b-ct2-int8")
        mock_urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
