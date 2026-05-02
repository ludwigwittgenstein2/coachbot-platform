from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from analytics.models import UsageLog
from bots.models import Chatbot, OllamaModel
from .models import Conversation, Message
from .ollama_client import OllamaError, ask_ollama


def guest_name(request):
    if request.method == "POST":
        guest_name_value = request.POST.get("guest_name", "").strip()
        next_url = request.POST.get("next", "/bots/")

        if guest_name_value:
            request.session["guest_name"] = guest_name_value
            return redirect(next_url)

    return render(request, "guest_name.html", {
        "next": request.GET.get("next", "/bots/")
    })


def guest_logout(request):
    request.session.pop("guest_name", None)
    return redirect("/")


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/bots/")
    else:
        form = UserCreationForm()

    return render(request, "register.html", {"form": form})


def start_chat(request):
    chatbot_id = request.GET.get("chatbot_id")
    model_id = request.GET.get("model_id")

    if not request.user.is_authenticated and not request.session.get("guest_name"):
        return redirect(f"/guest-name/?next={request.get_full_path()}")

    chatbot = get_object_or_404(Chatbot, id=chatbot_id, is_active=True)

    if model_id:
        model = get_object_or_404(OllamaModel, id=model_id, is_active=True)
    else:
        model = OllamaModel.objects.filter(is_active=True).first()

    if model is None:
        return JsonResponse({"error": "No active Ollama model found."}, status=400)

    conversation = Conversation.objects.create(
        user=request.user if request.user.is_authenticated else None,
        guest_name=request.session.get("guest_name", ""),
        chatbot=chatbot,
        model=model,
        title=f"{chatbot.name} session",
    )

    return redirect("chat_detail", conversation_id=conversation.id)


def chat_detail(request, conversation_id):
    if request.user.is_authenticated:
        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
            user=request.user,
        )
    else:
        guest_name_value = request.session.get("guest_name", "")

        if not guest_name_value:
            return redirect(f"/guest-name/?next={request.get_full_path()}")

        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
            guest_name=guest_name_value,
            user__isnull=True,
        )

    models = OllamaModel.objects.filter(is_active=True)

    return render(request, "conversations/chat.html", {
        "conversation": conversation,
        "models": models,
        "messages": conversation.messages.order_by("created_at"),
    })


@require_POST
def send_message(request, conversation_id):
    if request.user.is_authenticated:
        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
            user=request.user,
        )
    else:
        guest_name_value = request.session.get("guest_name", "")

        if not guest_name_value:
            return JsonResponse({"error": "Guest name required."}, status=403)

        conversation = get_object_or_404(
            Conversation,
            id=conversation_id,
            guest_name=guest_name_value,
            user__isnull=True,
        )

    user_message = request.POST.get("message", "").strip()
    model_id = request.POST.get("model_id") or conversation.model_id

    model = get_object_or_404(OllamaModel, id=model_id, is_active=True)

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    Message.objects.create(
        conversation=conversation,
        role="user",
        content=user_message,
        model_name=model.name,
    )

    history = [
        {"role": m.role, "content": m.content}
        for m in conversation.messages.exclude(role="system").order_by("created_at")[:20]
    ]

    try:
        reply = ask_ollama(
            model.name,
            conversation.chatbot.system_prompt,
            history[:-1],
            user_message,
        )
    except OllamaError as exc:
        reply = f"Error connecting to Ollama: {exc}"

    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content=reply,
        model_name=model.name,
    )

    conversation.model = model

    if conversation.messages.count() <= 2:
        conversation.title = user_message[:80]

    conversation.save()

    UsageLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        guest_name=conversation.guest_name,
        chatbot=conversation.chatbot,
        model=model,
        conversation=conversation,
        input_chars=len(user_message),
        output_chars=len(reply),
    )

    return JsonResponse({
        "reply": reply,
        "model": model.display_name,
    })


@login_required
def my_dashboard(request):
    conversations = Conversation.objects.filter(
        user=request.user
    ).select_related("chatbot", "model")

    total_messages = Message.objects.filter(
        conversation__user=request.user
    ).count()

    return render(request, "conversations/dashboard.html", {
        "conversations": conversations,
        "total_messages": total_messages,
    })