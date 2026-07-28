import json
from urllib.parse import urlencode

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from analytics.models import CoachbotFeedback, UsageLog
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
    """
    Determine how the CoachBot should respond based on the user's request.
    """
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
    """
    Combine platform-wide CoachBot rules with the selected bot's prompt.
    """
    return f"""
{COACHBOT_INTERACTION_RULES}

{get_pathway_rules(user_message)}

BOT-SPECIFIC INSTRUCTIONS:
{chatbot_system_prompt}
"""


def get_active_model_or_default(model_id=None):
    """
    Return the requested active model when available.

    If the requested model does not exist or is inactive, return the first
    available active model.
    """
    model = None

    if model_id:
        model = OllamaModel.objects.filter(
            id=model_id,
            is_active=True,
        ).first()

    if model is None:
        model = (
            OllamaModel.objects
            .filter(is_active=True)
            .order_by("id")
            .first()
        )

    return model


def get_conversation_for_request(request, conversation_id):
    """
    Retrieve a conversation belonging to the authenticated user or guest.

    Authenticated users can access only their own conversations.
    Guests can access only guest conversations associated with the guest
    name stored in their current session.
    """
    if request.user.is_authenticated:
        return get_object_or_404(
            Conversation,
            id=conversation_id,
            user=request.user,
        )

    guest_name_value = request.session.get("guest_name", "").strip()

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
    Safely retrieve the next URL from either GET or POST.

    External redirects are rejected.
    """
    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or default
    )

    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return default


def redirect_to_guest_name(request):
    """
    Redirect unauthenticated visitors to the guest-name page while
    preserving the original requested URL and query parameters.
    """
    next_url = request.get_full_path()
    query_string = urlencode({"next": next_url})

    return redirect(f"/guest-name/?{query_string}")


def guest_name(request):
    """
    Collect and store a guest user's display name in the session.
    """
    next_url = safe_next_url(
        request,
        default="/bots/",
    )

    if request.method == "POST":
        guest_name_value = request.POST.get(
            "guest_name",
            "",
        ).strip()

        if guest_name_value:
            request.session["guest_name"] = guest_name_value
            request.session["is_guest"] = True
            request.session.modified = True

            return redirect(next_url)

    return render(
        request,
        "guest_name.html",
        {
            "next": next_url,
        },
    )


def guest_logout(request):
    """
    Remove guest session information.
    """
    request.session.pop("guest_name", None)
    request.session.pop("is_guest", None)
    request.session.modified = True

    return redirect("/")


def register(request):
    """
    Register a standard Django user and sign the new user in.
    """
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

    return render(
        request,
        "register.html",
        {
            "form": form,
        },
    )


def start_chat(request):
    """
    Create a new conversation for either an authenticated user or guest.
    """
    chatbot_id = request.GET.get("chatbot_id")
    model_id = request.GET.get("model_id")

    if (
        not request.user.is_authenticated
        and not request.session.get("guest_name")
    ):
        return redirect_to_guest_name(request)

    if not chatbot_id:
        return JsonResponse(
            {
                "error": "chatbot_id is required.",
            },
            status=400,
        )

    chatbot = get_object_or_404(
        Chatbot,
        id=chatbot_id,
        is_active=True,
    )

    model = get_active_model_or_default(model_id)

    if model is None:
        return JsonResponse(
            {
                "error": "No active Ollama model found.",
            },
            status=400,
        )

    conversation = Conversation.objects.create(
        user=(
            request.user
            if request.user.is_authenticated
            else None
        ),
        guest_name=request.session.get("guest_name", ""),
        chatbot=chatbot,
        model=model,
        title=f"{chatbot.name} session",
    )

    return redirect(
        "chat_detail",
        conversation_id=conversation.id,
    )


def chat_detail(request, conversation_id):
    """
    Display a conversation and all active Ollama models.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return redirect_to_guest_name(request)

    models = (
        OllamaModel.objects
        .filter(is_active=True)
        .order_by("id")
    )

    messages = conversation.messages.order_by("created_at")

    return render(
        request,
        "conversations/chat.html",
        {
            "conversation": conversation,
            "models": models,
            "messages": messages,
        },
    )


def build_recent_history(conversation):
    """
    Build a short recent conversation history for Ollama.

    The newest user message has already been written to the database.
    Callers therefore pass history[:-1] to Ollama when the newest user
    message is supplied separately.
    """
    recent_messages = list(
        conversation.messages
        .exclude(role="system")
        .order_by("-created_at")[:4]
    )

    recent_messages.reverse()

    return [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in recent_messages
    ]


def save_assistant_result(
    request,
    conversation,
    model,
    user_message,
    reply,
):
    """
    Save the assistant response, update the conversation, and log usage.
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

    conversation.save(
        update_fields=[
            "model",
            "title",
        ]
    )

    UsageLog.objects.create(
        user=(
            request.user
            if request.user.is_authenticated
            else None
        ),
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
    Send a message using the standard non-streaming Ollama endpoint.

    This remains available as a fallback when streaming is not used.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {
                "error": "Guest name required.",
            },
            status=403,
        )

    user_message = request.POST.get(
        "message",
        "",
    ).strip()

    if not user_message:
        return JsonResponse(
            {
                "error": "Message cannot be empty.",
            },
            status=400,
        )

    requested_model_id = (
        request.POST.get("model_id")
        or conversation.model_id
    )

    model = get_active_model_or_default(
        requested_model_id
    )

    if model is None:
        return JsonResponse(
            {
                "error": "No active Ollama model found.",
            },
            status=400,
        )

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

    return JsonResponse(
        {
            "reply": reply,
            "model": model.display_name,
        }
    )


def sse_message(data, event=None):
    """
    Format a dictionary as a Server-Sent Event message.
    """
    lines = []

    if event:
        lines.append(f"event: {event}")

    lines.append(
        f"data: {json.dumps(data)}"
    )

    return "\n".join(lines) + "\n\n"


@require_POST
def send_message_stream(request, conversation_id):
    """
    Stream an Ollama response to the browser using Server-Sent Events.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {
                "error": "Guest name required.",
            },
            status=403,
        )

    user_message = request.POST.get(
        "message",
        "",
    ).strip()

    if not user_message:
        return JsonResponse(
            {
                "error": "Message cannot be empty.",
            },
            status=400,
        )

    requested_model_id = (
        request.POST.get("model_id")
        or conversation.model_id
    )

    model = get_active_model_or_default(
        requested_model_id
    )

    if model is None:
        return JsonResponse(
            {
                "error": "No active Ollama model found.",
            },
            status=400,
        )

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
            yield sse_message(
                {
                    "status": "started",
                },
                event="start",
            )

            for token in stream_ollama(
                model.name,
                system_prompt,
                history[:-1],
                user_message,
            ):
                chunks.append(token)

                yield sse_message(
                    {
                        "token": token,
                    },
                    event="token",
                )

            reply = "".join(chunks).strip()

            if not reply:
                reply = (
                    "I’m sorry, I could not generate a response."
                )

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
            error_reply = (
                f"Error connecting to Ollama: {exc}"
            )

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

        except Exception as exc:
            error_reply = (
                "An unexpected error occurred while generating "
                f"the response: {exc}"
            )

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


@require_POST
def submit_feedback(request, conversation_id):
    """
    Save or update end-of-conversation CoachBot feedback.

    Each conversation has one feedback record because CoachbotFeedback
    uses a OneToOneField. Submitting again updates the existing record.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {
                "error": (
                    "A guest name is required to submit feedback."
                ),
            },
            status=403,
        )

    try:
        request_body = request.body.decode("utf-8")
        payload = json.loads(request_body)

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return JsonResponse(
            {
                "error": "Invalid feedback request.",
            },
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {
                "error": "Invalid feedback request.",
            },
            status=400,
        )

    try:
        usefulness = int(
            payload.get("usefulness")
        )

        confidence = int(
            payload.get("confidence")
        )

    except (
        TypeError,
        ValueError,
    ):
        return JsonResponse(
            {
                "error": (
                    "Please answer both rating questions."
                ),
            },
            status=400,
        )

    improvement_feedback = payload.get(
        "improvement_feedback",
        "",
    )

    if improvement_feedback is None:
        improvement_feedback = ""

    if not isinstance(
        improvement_feedback,
        str,
    ):
        improvement_feedback = str(
            improvement_feedback
        )

    improvement_feedback = (
        improvement_feedback.strip()
    )

    if usefulness not in range(1, 6):
        return JsonResponse(
            {
                "error": (
                    "Usefulness must be between 1 and 5."
                ),
            },
            status=400,
        )

    if confidence not in range(1, 6):
        return JsonResponse(
            {
                "error": (
                    "Confidence must be between 1 and 5."
                ),
            },
            status=400,
        )

    if len(improvement_feedback) > 5000:
        return JsonResponse(
            {
                "error": (
                    "Open-ended feedback must be "
                    "5,000 characters or fewer."
                ),
            },
            status=400,
        )

    feedback, created = (
        CoachbotFeedback.objects.update_or_create(
            conversation=conversation,
            defaults={
                "usefulness": usefulness,
                "confidence": confidence,
                "improvement_feedback": (
                    improvement_feedback
                ),
            },
        )
    )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "feedback_id": feedback.id,
            "message": "Feedback saved successfully.",
        }
    )


@login_required
def my_dashboard(request):
    """
    Display the authenticated user's conversations and message total.
    """
    conversations = (
        Conversation.objects
        .filter(user=request.user)
        .select_related(
            "chatbot",
            "model",
        )
        .order_by("-created_at")
    )

    total_messages = Message.objects.filter(
        conversation__user=request.user
    ).count()

    return render(
        request,
        "conversations/dashboard.html",
        {
            "conversations": conversations,
            "total_messages": total_messages,
        },
    )