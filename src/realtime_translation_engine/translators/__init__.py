from __future__ import annotations

from dataclasses import dataclass

from ..translator import Translator
from ..translator import TranslationResult
from .llmpool import DEFAULT_LLM_RESPONSES_API_BASE_URL
from .llmpool import LlmResponsesTranslator
from .llmpool import render_translation_template


@dataclass
class DummyTranslator:
    mode: str = "marker"

    def translate(self, source_window: str) -> TranslationResult:
        if self.mode == "echo":
            return TranslationResult(text=source_window, model="dummy")
        if self.mode == "marker":
            return TranslationResult(
                text=f"[TRANSLATED] {source_window}" if source_window else "",
                model="dummy",
            )
        raise ValueError(f"unsupported dummy translator mode: {self.mode!r}")

    def run_second_pass(
        self,
        source_window: str,
        draft_translation: str,
        *,
        system_prompt: str | None = None,
    ) -> TranslationResult:
        del source_window
        del system_prompt
        return TranslationResult(text=draft_translation, model="dummy")


def build_translator(
    name: str,
    *,
    dummy_mode: str = "marker",
    service_model: str | None = None,
    second_pass_model: str | None = None,
    first_pass_prompt: str | None = None,
    first_pass_input_template: str | None = None,
    first_pass_inline_user_prompt: bool = False,
    second_pass_inline_user_prompt: bool = False,
    second_pass_input_template: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
) -> Translator:
    if name == "dummy":
        return DummyTranslator(mode=dummy_mode)
    if name == "llm-responses":
        translator_kwargs: dict[str, str | bool] = {}
        if service_model:
            translator_kwargs["model"] = service_model
        if second_pass_model is not None:
            translator_kwargs["second_pass_model"] = second_pass_model
        if first_pass_prompt is not None:
            translator_kwargs["first_pass_prompt"] = first_pass_prompt
        if first_pass_input_template is not None:
            translator_kwargs["first_pass_input_template"] = first_pass_input_template
        if first_pass_inline_user_prompt:
            translator_kwargs["first_pass_inline_user_prompt"] = True
        if second_pass_inline_user_prompt:
            translator_kwargs["second_pass_inline_user_prompt"] = True
        if second_pass_input_template is not None:
            translator_kwargs["second_pass_input_template"] = second_pass_input_template
        if source_language is not None:
            translator_kwargs["source_language"] = source_language
        if target_language is not None:
            translator_kwargs["target_language"] = target_language
        return LlmResponsesTranslator(**translator_kwargs)
    raise ValueError(f"unsupported translator: {name!r}")


__all__ = [
    "DEFAULT_LLM_RESPONSES_API_BASE_URL",
    "DummyTranslator",
    "LlmResponsesTranslator",
    "build_translator",
    "render_translation_template",
]
