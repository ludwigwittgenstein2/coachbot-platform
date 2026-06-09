import json
import requests
from django.conf import settings


class OllamaError(Exception):
    pass


def build_messages(system_prompt, history, user_message):
    messages = [{"role": "system", "content": system_prompt}]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_message})
    return messages


def get_ollama_payload(model_name, messages, stream=False):
    return {
        "model": model_name,
        "messages": messages,
        "stream": stream,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.2,
            "top_p": 0.8,
            "num_predict": -1,
            "num_ctx": 4096,
            "repeat_penalty": 1.1,
        },
    }


def ask_ollama(model_name, system_prompt, history, user_message):
    """
    Non-streaming fallback.
    Keeps your existing JSON-based chat behavior working.
    """
    messages = build_messages(system_prompt, history, user_message)
    payload = get_ollama_payload(model_name, messages, stream=False)

    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()

        data = response.json()
        content = data.get("message", {}).get("content", "")

        if not content:
            raise OllamaError("Ollama returned an empty response.")

        return content.strip()

    except requests.exceptions.Timeout as exc:
        raise OllamaError("Ollama request timed out.") from exc

    except requests.exceptions.ConnectionError as exc:
        raise OllamaError(
            f"Could not connect to Ollama at {settings.OLLAMA_BASE_URL}."
        ) from exc

    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response else "unknown"
        response_text = exc.response.text if exc.response else ""
        raise OllamaError(f"Ollama HTTP error {status_code}: {response_text}") from exc

    except ValueError as exc:
        raise OllamaError("Ollama returned invalid JSON.") from exc

    except Exception as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc


def stream_ollama(model_name, system_prompt, history, user_message):
    """
    Streaming generator.
    Yields text chunks as Ollama produces them.
    """
    messages = build_messages(system_prompt, history, user_message)
    payload = get_ollama_payload(model_name, messages, stream=True)

    try:
        with requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            stream=True,
            timeout=600,
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if data.get("done"):
                    break

                token = data.get("message", {}).get("content", "")

                if token:
                    yield token

    except requests.exceptions.Timeout as exc:
        raise OllamaError("Ollama streaming request timed out.") from exc

    except requests.exceptions.ConnectionError as exc:
        raise OllamaError(
            f"Could not connect to Ollama at {settings.OLLAMA_BASE_URL}."
        ) from exc

    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response else "unknown"
        response_text = exc.response.text if exc.response else ""
        raise OllamaError(f"Ollama HTTP error {status_code}: {response_text}") from exc

    except Exception as exc:
        raise OllamaError(f"Ollama streaming request failed: {exc}") from exc