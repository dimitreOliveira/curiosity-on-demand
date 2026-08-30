"""Base agent abstraction wrapping the Google GenAI SDK with structured output validation."""

import logging
from typing import TypeVar, cast

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseAgent:
    """Base class for all Gemini-powered autonomous pipeline agents."""

    def __init__(
        self,
        settings: Settings | None = None,
        model_name: str | None = None,
    ):
        self.settings = settings or get_settings()
        self.model_name = model_name or self.settings.gemini_model

        # Initialize the official Google GenAI Client
        # If gemini_api_key is empty, the SDK will look for GEMINI_API_KEY in os.environ
        if self.settings.gemini_api_key:
            self.client = genai.Client(api_key=self.settings.gemini_api_key)
        else:
            self.client = genai.Client()

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        tools: list[types.Tool] | None = None,
        model: str | None = None,
    ) -> str:
        """Generate text from Gemini (ideal for search-grounded research with tools)."""
        target_model = model or self.model_name
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        logger.debug("Generating text with model %s", target_model)
        response = await self.client.aio.models.generate_content(
            model=target_model,
            contents=prompt,
            config=config,
        )

        if not response or not response.text:
            raise RuntimeError(
                f"Empty response returned by Gemini model '{target_model}'"
            )

        return response.text.strip()

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        system_instruction: str | None = None,
        tools: list[types.Tool] | None = None,
        model: str | None = None,
    ) -> T:
        """Generate strongly-typed structured output validated against a Pydantic schema."""
        target_model = model or self.model_name
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            tools=tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        logger.debug(
            "Generating structured output for %s with model %s",
            response_schema.__name__,
            target_model,
        )
        response = await self.client.aio.models.generate_content(
            model=target_model,
            contents=prompt,
            config=config,
        )

        if not response:
            raise RuntimeError(
                f"No response returned by Gemini model '{target_model}' for schema '{response_schema.__name__}'"
            )

        if response.parsed:
            return cast(T, response.parsed)

        # Fallback: attempt manual validation if response.parsed is None
        if response.text:
            text = response.text.strip()
            text = text.removeprefix("```json")
            text = text.removeprefix("```")
            text = text.removesuffix("```")
            text = text.strip()
            try:
                return response_schema.model_validate_json(text)
            except (ValidationError, ValueError) as err:
                logger.error(
                    "Failed to parse response text as %s: %s",
                    response_schema.__name__,
                    err,
                )

        raise RuntimeError(
            f"Empty or unparsable response returned by Gemini model '{target_model}' for schema '{response_schema.__name__}'"
        )
