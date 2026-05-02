import requests
from django.conf import settings

class OllamaError(Exception):
    pass

def ask_ollama(model_name, system_prompt, history, user_message):
    messages = [{'role': 'system', 'content': system_prompt}]
    messages.extend(history)
    messages.append({'role': 'user', 'content': user_message})
    try:
        response = requests.post(
            f'{settings.OLLAMA_BASE_URL}/api/chat',
            json={'model': model_name, 'messages': messages, 'stream': False},
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return data['message']['content']
    except Exception as exc:
        raise OllamaError(f'Ollama request failed: {exc}') from exc
