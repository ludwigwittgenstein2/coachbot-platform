import json
from urllib.parse import urlencode

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from analytics.models import UsageLog
from bots.models import Chatbot, OllamaModel
from .models import Conversation, Message
from .ollama_client import OllamaError, ask_ollama, stream_ollama


COACHBOT_INTERACTION_RULES = """
You are a framework-specific CoachBot, not a generic chatbot.

The BOT-SPECIFIC INSTRUCTIONS are the source of truth.
Never invent, rename, or redefine the framework from general memory.
If the user asks what the framework is, explain it using only the bot-specific instructions.

Core identity rules:
- If the user asks "what are you?", say you are this specific CoachBot and name the selected framework.
- Do not answer as a generic AI assistant.
- Stay inside the selected CoachBot's framework.
- If the selected bot is RISE, RISE means Rapport, Interest, Social Norms, and Effective Messaging.
- If the selected bot is DESC, DESC means Describe, Express, Specify, and Consequences.
- If the selected bot is SEA, SEA means State, Explain, and Ask.
- If the selected bot is PAUSE, PAUSE means Pay Attention, Acknowledge, Understand, Seek, and Examine.

User-example-first policy:
- The CoachBot should use the learner's own situation, example, draft message, or conversation whenever possible.
- Do not invent your own examples, scenarios, scripts, role-plays, sample conversations, sample messages, or fictional cases.
- Even if the learner asks for an example, first ask the learner to provide their own real or realistic situation.
- If the learner says they do not have a real situation, ask them to create a simple realistic situation from their own work, school, family, team, or community context.
- Do not provide a ready-made example unless the learner explicitly insists after being asked for their own situation.
- For Practice, Coaching, Scenario, and Training requests, the default response must ask for the learner's own context first.
- When the learner provides their own situation, use that situation directly and help them apply the framework step by step.

Answer-length rules:
- Do not cut answers short.
- Give complete answers when the user asks for explanation.
- Use clear structure with headings or bullets when helpful.
- Learn requests may explain the whole framework clearly.
- Practice and Coaching requests should not become long lectures; they should ask for the user's own situation first.

Interaction rules:
- Do not answer your own question.
- Do not role-play both sides of a conversation unless the learner explicitly insists after providing their own situation.
- Do not critique a learner response until the learner has actually responded.
- Ask only one main question at the end when a question is needed.
- Avoid vague endings like “How does that sound?” or “What do you think?”
- Use a specific learning-oriented prompt.
"""


def get_pathway_rules(user_message):
    msg = user_message.lower()

    user_is_asking_for_application = (
        "practice" in msg
        or "coach" in msg
        or "my situation" in msg
        or "help me use" in msg
        or "scenario" in msg
        or "training" in msg
        or "role play" in msg
        or "roleplay" in msg
        or "example" in msg
        or "sample" in msg
        or "show me" in msg
    )

    user_is_asking_for_explanation = (
        "learn" in msg
        or "what is" in msg
        or "explain" in msg
        or "define" in msg
        or "how does" in msg
        or "what are you" in msg
    )

    if user_is_asking_for_application:
        return """
CURRENT PATHWAY: USER-CONTEXT APPLICATION

Behavior:
- Do not create your own example, scenario, script, role-play, sample message, or fictional case.
- Ask the learner for their own real or realistic situation.
- Ask for only the minimum context needed to begin.
- Do not answer for the learner.
- Do not critique until the learner gives a response or draft.
- End with one specific question asking for the learner's own situation, draft, or conversation.
"""

    if user_is_asking_for_explanation:
        return """
CURRENT PATHWAY: LEARN / EXPLANATION

Behavior:
- Give a complete and accurate explanation of the selected framework.
- Use the bot-specific instructions as the source of truth.
- Do not invent different meanings for the framework letters.
- Do not include fictional examples.
- After explaining, invite the learner to share their own real or realistic situation if they want to apply it.
- End with one useful follow-up question if appropriate.
"""

    return """
CURRENT PATHWAY: GENERAL

Behavior:
- Stay inside the selected CoachBot framework.
- Give a complete answer if the user asks for information.
- Do not provide fictional examples.
- When the user wants help applying the framework, ask for their own real or realistic situation.
- Ask one useful follow-up question if needed.
"""


def build_coachbot_system_prompt(chatbot_system_prompt, user_message):
    return f"""
{COACHBOT_INTERACTION_RULES}

{get_pathway_rules(user_message)}

BOT-SPECIFIC INSTRUCTIONS:
{chatbot_system_prompt}
"""


def get_active_model_or_default(model_id=None):
    """
    Return the requested active model if available.
    Otherwise, fall back to the first active model.

    This prevents old conversations from breaking after old models are deactivated.
    """
    model = None

    if model_id:
        model = OllamaModel.objects.filter(
            id=model_id,
            is_active=True,
        ).first()

    if model is None:
        model = OllamaModel.objects.filter(
            is_active=True,
        ).order_by("id").first()

    return model


def get_conversation_for_request(request, conversation_id):
    """
    Fetch the correct conversation for either authenticated users or guests.
    """
    if request.user.is_authenticated:
        return get_object_or_404(
            Conversation,
            id=conversation_id,
            user=request.user,
        )

    guest_name_value = request.session.get("guest_name", "")

    if not guest_name_value:
        return None

    return get_object_or_404(
        Conversation,
        id=conversation_id,
        guest_name=guest_name_value,
        user__isnull=True,
    )


def safe_next_url(request, default="/bots/"):
    """
    Safely read the next URL from GET or POST.
    Prevents broken redirects and avoids unsafe external redirects.
    """
    next_url = request.POST.get("next") or request.GET.get("next") or default

    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return default


def redirect_to_guest_name(request):
    """
    Redirect unauthenticated users to guest-name page while preserving
    the full original URL, including query params like model_id.
    """
    next_url = request.get_full_path()
    query_string = urlencode({"next": next_url})
    return redirect(f"/guest-name/?{query_string}")


def guest_name(request):
    next_url = safe_next_url(request, default="/bots/")

    if request.method == "POST":
        guest_name_value = request.POST.get("guest_name", "").strip()

        if guest_name_value:
            request.session["guest_name"] = guest_name_value
            request.session["is_guest"] = True
            request.session.modified = True
            return redirect(next_url)

    return render(request, "guest_name.html", {
        "next": next_url,
    })


def guest_logout(request):
    request.session.pop("guest_name", None)
    request.session.pop("is_guest", None)
    request.session.modified = True
    return redirect("/")


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)

            request.session.pop("guest_name", None)
            request.session.pop("is_guest", None)
            request.session.modified = True

            return redirect("/bots/")
    else:
        form = UserCreationForm()

    return render(request, "register.html", {"form": form})


def start_chat(request):
    chatbot_id = request.GET.get("chatbot_id")
    model_id = request.GET.get("model_id")

    if not request.user.is_authenticated and not request.session.get("guest_name"):
        return redirect_to_guest_name(request)

    if not chatbot_id:
        return JsonResponse({"error": "chatbot_id is required."}, status=400)

    chatbot = get_object_or_404(Chatbot, id=chatbot_id, is_active=True)

    model = get_active_model_or_default(model_id)

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
    conversation = get_conversation_for_request(request, conversation_id)

    if conversation is None:
        return redirect_to_guest_name(request)

    models = OllamaModel.objects.filter(is_active=True).order_by("id")

    return render(request, "conversations/chat.html", {
        "conversation": conversation,
        "models": models,
        "messages": conversation.messages.order_by("created_at"),
    })


def build_recent_history(conversation):
    """
    Build a short recent history for Ollama.
    The latest user message is included in the DB already,
    so callers use history[:-1] when sending the separate user_message.
    """
    recent_messages = list(
        conversation.messages
        .exclude(role="system")
        .order_by("-created_at")[:4]
    )
    recent_messages.reverse()

    return [
        {"role": m.role, "content": m.content}
        for m in recent_messages
    ]


def save_assistant_result(request, conversation, model, user_message, reply):
    """
    Save assistant message, update conversation metadata, and log usage.
    """
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


@require_POST
def send_message(request, conversation_id):
    """
    Standard non-streaming endpoint.
    Keep this as a fallback.
    """
    conversation = get_conversation_for_request(request, conversation_id)

    if conversation is None:
        return JsonResponse({"error": "Guest name required."}, status=403)

    user_message = request.POST.get("message", "").strip()

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    requested_model_id = request.POST.get("model_id") or conversation.model_id
    model = get_active_model_or_default(requested_model_id)

    if model is None:
        return JsonResponse({"error": "No active Ollama model found."}, status=400)

    Message.objects.create(
        conversation=conversation,
        role="user",
        content=user_message,
        model_name=model.name,
    )

    history = build_recent_history(conversation)

    system_prompt = build_coachbot_system_prompt(
        conversation.chatbot.system_prompt,
        user_message,
    )

    try:
        reply = ask_ollama(
            model.name,
            system_prompt,
            history[:-1],
            user_message,
        )
    except OllamaError as exc:
        reply = f"Error connecting to Ollama: {exc}"

    save_assistant_result(
        request=request,
        conversation=conversation,
        model=model,
        user_message=user_message,
        reply=reply,
    )

    return JsonResponse({
        "reply": reply,
        "model": model.display_name,
    })


def sse_message(data, event=None):
    """
    Format data as a Server-Sent Event message.
    """
    lines = []

    if event:
        lines.append(f"event: {event}")

    lines.append(f"data: {json.dumps(data)}")

    return "\n".join(lines) + "\n\n"


@require_POST
def send_message_stream(request, conversation_id):
    """
    Streaming endpoint.
    Sends tokens to the browser as Ollama generates them.
    """
    conversation = get_conversation_for_request(request, conversation_id)

    if conversation is None:
        return JsonResponse({"error": "Guest name required."}, status=403)

    user_message = request.POST.get("message", "").strip()

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    requested_model_id = request.POST.get("model_id") or conversation.model_id
    model = get_active_model_or_default(requested_model_id)

    if model is None:
        return JsonResponse({"error": "No active Ollama model found."}, status=400)

    Message.objects.create(
        conversation=conversation,
        role="user",
        content=user_message,
        model_name=model.name,
    )

    history = build_recent_history(conversation)

    system_prompt = build_coachbot_system_prompt(
        conversation.chatbot.system_prompt,
        user_message,
    )

    def event_stream():
        chunks = []

        try:
            yield sse_message({"status": "started"}, event="start")

            for token in stream_ollama(
                model.name,
                system_prompt,
                history[:-1],
                user_message,
            ):
                chunks.append(token)
                yield sse_message({"token": token}, event="token")

            reply = "".join(chunks).strip()

            if not reply:
                reply = "I’m sorry, I could not generate a response."

            save_assistant_result(
                request=request,
                conversation=conversation,
                model=model,
                user_message=user_message,
                reply=reply,
            )

            yield sse_message(
                {
                    "status": "done",
                    "reply": reply,
                    "model": model.display_name,
                },
                event="done",
            )

        except OllamaError as exc:
            error_reply = f"Error connecting to Ollama: {exc}"

            save_assistant_result(
                request=request,
                conversation=conversation,
                model=model,
                user_message=user_message,
                reply=error_reply,
            )

            yield sse_message(
                {
                    "status": "error",
                    "error": error_reply,
                },
                event="error",
            )

    response = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )

    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    return response


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