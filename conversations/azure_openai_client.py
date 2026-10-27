from django.conf import settings
from azure.identity import (
    DefaultAzureCredential,
    get_bearer_token_provider,
)
from openai import OpenAI

from .ollama_client import build_messages


class AzureOpenAIError(Exception):
    pass


def get_azure_client():
    credential = DefaultAzureCredential(
        managed_identity_client_id=settings.AZURE_CLIENT_ID
    )

    token_provider = get_bearer_token_provider(
        credential,
        "https://cognitiveservices.azure.com/.default",
    )

    return OpenAI(
        base_url=(
            settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
            + "/openai/v1/"
        ),
        api_key=token_provider,
        timeout=300,
    )


def ask_azure(model_name, system_prompt, history, user_message):
    messages = build_messages(
        system_prompt, history, user_message
    )

    try:
        response = get_azure_client().chat.completions.create(
            model=model_name,
            messages=messages,
        )

        content = response.choices[0].message.content
        if not content:
            raise AzureOpenAIError("Azure returned an empty response.")

        return content.strip()

    except Exception as exc:
        raise AzureOpenAIError(
            f"Azure OpenAI request failed: {exc}"
        ) from exc


def stream_azure(model_name, system_prompt, history, user_message):
    messages = build_messages(
        system_prompt, history, user_message
    )

    try:
        stream = get_azure_client().chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue

            content = chunk.choices[0].delta.content

            if content:
                yield content

    except Exception as exc:
        raise AzureOpenAIError(
            f"Azure OpenAI streaming failed: {exc}"
        ) from exc