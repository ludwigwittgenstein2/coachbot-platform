import requests
from django.conf import settings


class OllamaError(Exception):
    pass


def ask_ollama(model_name, system_prompt, history, user_message):
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,

        # Keeps model loaded after first request.
        # This reduces repeated cold-loading delay.
        "keep_alive": "24h",

        # Controls speed + response length.
        "options": {
            "num_ctx": 2048,
            "num_predict": 400,
            "temperature": 0.2,
            "top_p": 0.75,
            "repeat_penalty": 1.15,
        },
    }

    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "").strip()

    except requests.RequestException as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc

    except KeyError as exc:
        raise OllamaError(f"Unexpected Ollama response format: {exc}") from exc