"""Base agent abstraction wrapping the Google GenAI SDK with structured output validation."""

import json
import logging
import re
from typing import Any, TypeVar

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
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        """Generate unstructured text from Gemini."""
        target_model = model or self.model_name
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature
            if temperature is not None
            else self.settings.gemini_temperature,
            tools=tools,
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
        temperature: float | None = None,
        model: str | None = None,
    ) -> T:
        """Generate strongly-typed structured output validated against a Pydantic schema."""
        target_model = model or self.model_name
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature
            if temperature is not None
            else self.settings.gemini_temperature,
            response_mime_type="application/json",
            response_schema=response_schema,
            tools=tools,
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

        # 1. Check if SDK parsed object directly
        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, response_schema):
                return response.parsed
            if isinstance(response.parsed, dict):
                return response_schema.model_validate(response.parsed)

        # 2. Parse from response.text
        if not response or not response.text:
            raise RuntimeError(
                f"Empty response returned for schema '{response_schema.__name__}'"
            )

        raw_text = response.text.strip()

        # Clean JSON markdown fences if present
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)
            raw_text = raw_text.strip()

        try:
            return response_schema.model_validate_json(raw_text)
        except (ValidationError, ValueError, TypeError) as err:
            logger.warning(
                "Direct JSON validation failed, attempting object parse: %s",
                err,
            )
            data: Any = json.loads(raw_text)
            return response_schema.model_validate(data)
