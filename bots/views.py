from django.shortcuts import render

from .models import Chatbot, OllamaModel


def bot_list(request):
    bots = Chatbot.objects.filter(is_active=True)
    models = OllamaModel.objects.filter(is_active=True)

    return render(request, "bots/list.html", {
        "bots": bots,
        "models": models,
    })