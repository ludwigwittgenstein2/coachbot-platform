from django.conf import settings
from django.shortcuts import render

from .models import Chatbot, OllamaModel


def bot_list(request):
    """
    Display active CoachBots and models available
    for the configured inference backend.
    """

    bots = Chatbot.objects.filter(is_active=True)

    models = OllamaModel.objects.filter(is_active=True)

    backend = getattr(settings, "LLM_BACKEND", "ollama").lower()

    if backend == "azure":
        models = models.filter(
            name=settings.AZURE_OPENAI_DEPLOYMENT
        )
    else:
        models = models.exclude(
            name=settings.AZURE_OPENAI_DEPLOYMENT
        )

    models = models.order_by("id")

    return render(
        request,
        "bots/list.html",
        {
            "bots": bots,
            "models": models,
        },
    )
