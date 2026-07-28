import json
import logging
import uuid
from urllib.parse import urlencode

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from analytics.models import CoachbotFeedback, UsageLog
from bots.models import Chatbot, OllamaModel

from .models import Conversation, Message
from .ollama_client import OllamaError, ask_ollama, stream_ollama


logger = logging.getLogger(__name__)


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

    Otherwise, return the first active model.
    """
    model = None

    if model_id:
        try:
            model = OllamaModel.objects.filter(
                id=model_id,
                is_active=True,
            ).first()
        except (TypeError, ValueError):
            model = None

    if model is None:
        model = (
            OllamaModel.objects
            .filter(is_active=True)
            .order_by("id")
            .first()
        )

    return model


def get_or_create_visitor_id(request):
    """
    Return a persistent random browser identifier.

    This is mainly used to recognize repeat guest users. Authenticated
    users are identified through their Django user account.
    """
    visitor_id = request.session.get("visitor_id", "").strip()

    if not visitor_id:
        visitor_id = uuid.uuid4().hex
        request.session["visitor_id"] = visitor_id
        request.session.modified = True

    return visitor_id


def get_conversation_for_request(request, conversation_id):
    """
    Retrieve a conversation belonging to the current user or guest.
    """
    if request.user.is_authenticated:
        return get_object_or_404(
            Conversation,
            id=conversation_id,
            user=request.user,
        )

    guest_name_value = request.session.get(
        "guest_name",
        "",
    ).strip()

    if not guest_name_value:
        return None

    visitor_id = request.session.get(
        "visitor_id",
        "",
    ).strip()

    if visitor_id:
        return get_object_or_404(
            Conversation,
            id=conversation_id,
            guest_name=guest_name_value,
            visitor_id=visitor_id,
            user__isnull=True,
        )

    # Legacy fallback for conversations created before visitor_id existed.
    return get_object_or_404(
        Conversation,
        id=conversation_id,
        guest_name=guest_name_value,
        user__isnull=True,
    )


def safe_next_url(request, default="/bots/"):
    """
    Safely retrieve a local redirect URL from GET or POST.
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
    Redirect an unauthenticated visitor to the guest-name page while
    preserving the original requested URL.
    """
    next_url = request.get_full_path()
    query_string = urlencode({"next": next_url})

    return redirect(f"/guest-name/?{query_string}")


def guest_name(request):
    """
    Store the guest's display name in the Django session.
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
            get_or_create_visitor_id(request)

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
    End the named guest session.

    visitor_id is intentionally preserved so the same browser can still
    be recognized as a repeat guest later.
    """
    request.session.pop("guest_name", None)
    request.session.pop("is_guest", None)
    request.session.modified = True

    return redirect("/")


def register(request):
    """
    Register a standard Django user and sign them in.
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
    Create a new CoachBot conversation.
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
            {"error": "chatbot_id is required."},
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
            {"error": "No active Ollama model found."},
            status=400,
        )

    visitor_id = get_or_create_visitor_id(request)

    conversation = Conversation.objects.create(
        user=(
            request.user
            if request.user.is_authenticated
            else None
        ),
        guest_name=request.session.get(
            "guest_name",
            "",
        ),
        visitor_id=visitor_id,
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
    Display a CoachBot conversation.
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

    messages = conversation.messages.order_by(
        "created_at"
    )

    feedback_submitted = (
        CoachbotFeedback.objects
        .filter(conversation=conversation)
        .exists()
    )

    return render(
        request,
        "conversations/chat.html",
        {
            "conversation": conversation,
            "models": models,
            "messages": messages,
            "feedback_submitted": feedback_submitted,
        },
    )


def build_recent_history(conversation):
    """
    Build a short recent message history for Ollama.
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
    Save the assistant message and create a usage log.
    """
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content=reply,
        model_name=model.name,
    )

    conversation.model = model
    conversation.updated_at = timezone.now()

    if conversation.messages.count() <= 2:
        conversation.title = user_message[:80]

    conversation.save(
        update_fields=[
            "model",
            "title",
            "updated_at",
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
    Non-streaming message endpoint.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {"error": "Conversation access denied."},
            status=403,
        )

    user_message = request.POST.get(
        "message",
        "",
    ).strip()

    if not user_message:
        return JsonResponse(
            {"error": "Message cannot be empty."},
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
            {"error": "No active Ollama model found."},
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
    Format data as a Server-Sent Event message.
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
    Stream an Ollama response through Server-Sent Events.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {"error": "Conversation access denied."},
            status=403,
        )

    user_message = request.POST.get(
        "message",
        "",
    ).strip()

    if not user_message:
        return JsonResponse(
            {"error": "Message cannot be empty."},
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
            {"error": "No active Ollama model found."},
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
                {"status": "started"},
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
                    {"token": token},
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

        except Exception:
            logger.exception(
                "Unexpected streaming error for conversation %s",
                conversation.id,
            )

            yield sse_message(
                {
                    "status": "error",
                    "error": (
                        "An unexpected error occurred while "
                        "generating the response."
                    ),
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
def record_activity(request, conversation_id):
    """
    Record a short interval of active application use.

    The browser should call this endpoint approximately every 15 seconds
    while the tab is visible and the participant is active.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {"error": "Conversation access denied."},
            status=403,
        )

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

        requested_seconds = int(
            payload.get("seconds", 15)
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return JsonResponse(
            {"error": "Invalid activity data."},
            status=400,
        )

    requested_seconds = max(
        1,
        min(requested_seconds, 30),
    )

    now = timezone.now()

    with transaction.atomic():
        locked_conversation = (
            Conversation.objects
            .select_for_update()
            .get(pk=conversation.pk)
        )

        if locked_conversation.session_ended_at:
            return JsonResponse(
                {
                    "success": True,
                    "ignored": True,
                    "active_seconds": (
                        locked_conversation.active_seconds
                    ),
                }
            )

        if locked_conversation.last_activity_at:
            seconds_since_last_update = (
                now
                - locked_conversation.last_activity_at
            ).total_seconds()

            if seconds_since_last_update < 8:
                return JsonResponse(
                    {
                        "success": True,
                        "ignored": True,
                        "active_seconds": (
                            locked_conversation.active_seconds
                        ),
                    }
                )

        locked_conversation.active_seconds += (
            requested_seconds
        )

        locked_conversation.last_activity_at = now

        locked_conversation.save(
            update_fields=[
                "active_seconds",
                "last_activity_at",
            ]
        )

    return JsonResponse(
        {
            "success": True,
            "active_seconds": (
                locked_conversation.active_seconds
            ),
        }
    )


@require_POST
def submit_feedback(request, conversation_id):
    """
    Save feedback, duration, visit number, and repeat-user status.
    """
    conversation = get_conversation_for_request(
        request,
        conversation_id,
    )

    if conversation is None:
        return JsonResponse(
            {"error": "Conversation access denied."},
            status=403,
        )

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return JsonResponse(
            {"error": "Invalid feedback request."},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"error": "Invalid feedback request."},
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
                )
            },
            status=400,
        )

    improvement_feedback = payload.get(
        "improvement_feedback",
        "",
    )

    if improvement_feedback is None:
        improvement_feedback = ""

    improvement_feedback = str(
        improvement_feedback
    ).strip()

    if usefulness not in range(1, 6):
        return JsonResponse(
            {
                "error": (
                    "Usefulness must be between 1 and 5."
                )
            },
            status=400,
        )

    if confidence not in range(1, 6):
        return JsonResponse(
            {
                "error": (
                    "Confidence must be between 1 and 5."
                )
            },
            status=400,
        )

    if len(improvement_feedback) > 5000:
        return JsonResponse(
            {
                "error": (
                    "Open-ended feedback must be "
                    "5,000 characters or fewer."
                )
            },
            status=400,
        )

    if conversation.user_id:
        prior_conversations = (
            Conversation.objects
            .filter(
                user_id=conversation.user_id,
                messages__role="user",
            )
            .exclude(pk=conversation.pk)
            .distinct()
        )

    elif conversation.visitor_id:
        prior_conversations = (
            Conversation.objects
            .filter(
                user__isnull=True,
                visitor_id=conversation.visitor_id,
                messages__role="user",
            )
            .exclude(pk=conversation.pk)
            .distinct()
        )

    else:
        prior_conversations = (
            Conversation.objects.none()
        )

    previous_visit_count = (
        prior_conversations.count()
    )

    visit_number = previous_visit_count + 1
    is_repeat_user = previous_visit_count > 0

    with transaction.atomic():
        locked_conversation = (
            Conversation.objects
            .select_for_update()
            .get(pk=conversation.pk)
        )

        if locked_conversation.session_ended_at is None:
            locked_conversation.session_ended_at = (
                timezone.now()
            )

            locked_conversation.save(
                update_fields=[
                    "session_ended_at",
                ]
            )

        feedback, created = (
            CoachbotFeedback.objects.update_or_create(
                conversation=locked_conversation,
                defaults={
                    "usefulness": usefulness,
                    "confidence": confidence,
                    "improvement_feedback": (
                        improvement_feedback
                    ),
                    "session_duration_seconds": (
                        locked_conversation.active_seconds
                    ),
                    "is_repeat_user": is_repeat_user,
                    "visit_number": visit_number,
                },
            )
        )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "feedback_id": feedback.id,
            "session_duration_seconds": (
                feedback.session_duration_seconds
            ),
            "is_repeat_user": feedback.is_repeat_user,
            "visit_number": feedback.visit_number,
            "message": "Feedback saved successfully.",
        }
    )


@login_required
def my_dashboard(request):
    """
    Display the authenticated user's conversations.
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