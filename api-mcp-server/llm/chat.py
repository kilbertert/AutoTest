# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
import os
import logging
from dotenv import load_dotenv
from typing import Union

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MODEL_NAME = "azure gpt-4o 2025-01-01-preview"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 60
DEFAULT_LOCAL_LM_ENDPOINT = "http://localhost:11434"

# Environment variable names for configuration
AZURE_OPENAI_API_KEY = "AZURE_OPENAI_API_KEY"
AZURE_OPENAI_ENDPOINT_ENV = "AZURE_OPENAI_ENDPOINT"


class LLMClient:
    """
    A client for interacting with various LLM providers for API testing.

    """

    def __init__(self):
        load_dotenv()
        self.model_name = DEFAULT_MODEL_NAME
        self.temperature = DEFAULT_TEMPERATURE
        self.max_tokens = DEFAULT_MAX_TOKENS
        self.max_retries = DEFAULT_MAX_RETRIES
        self.timeout = DEFAULT_TIMEOUT
        self.api_key = os.getenv(AZURE_OPENAI_API_KEY)
        self.azure_endpoint = os.getenv(AZURE_OPENAI_ENDPOINT_ENV)
        self.local_lm_endpoint = DEFAULT_LOCAL_LM_ENDPOINT
        logging.info(f"LLMClient initialized with: {self.__dict__}")

    def get_azure_model(
        self,
    ) -> Union[ChatOpenAI, ChatGoogleGenerativeAI, ChatAnthropic, AzureChatOpenAI]:
        """
        Returns an instance of the appropriate chat model based on the model name.

        Raises:
            ValueError: If the model name is invalid or required environment variables are not set.
        """
        # currently only support Azure OpenAI
        if self.model_name.startswith("azure"):
            items = self.model_name.split()
            if len(items) < 2:
                raise ValueError("Azure model name must be in the format 'azure <deployment_name> <api_version>'")

            if not self.api_key:
                raise ValueError(f"{AZURE_OPENAI_API_KEY} environment variable is not set")

            if not self.azure_endpoint:
                raise ValueError(f"{AZURE_OPENAI_ENDPOINT_ENV} environment variable is not set")

            return AzureChatOpenAI(
                azure_deployment=items[1],
                api_version=items[2],
                azure_endpoint=self.azure_endpoint,
                temperature=self.temperature,
                api_key=self.api_key,
                max_tokens=self.max_tokens,
                max_retries=self.max_retries,
                timeout=self.timeout,
            )
        else:
            raise ValueError(f"Unsupported model name: {self.model_name}")

    def azure_gpt_available(self) -> bool:
        return self.api_key is not None and self.azure_endpoint is not None

    def local_copilot_available(self) -> bool:
        import requests
        url_tag = f"{self.local_lm_endpoint}/api/tags"
        try:
            response = requests.get(url_tag, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                models = [model["name"] for model in models]
                if "gpt-5.4" in models:
                    return True
                else:
                    logging.warning("gpt-5.4 model not found in local copilot tags.")
                    return False
            else:
                logging.error(f"Failed to check local copilot availability: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logging.error(f"Error checking local copilot availability: {repr(e)}")
            return False
        return False


def is_ai_enabled() -> bool:
    """Check if AI functionality is properly configured."""
    client = LLMClient()
    return client.azure_gpt_available() or client.local_copilot_available()
