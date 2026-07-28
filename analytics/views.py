from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import (
    Avg,
    Count,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render

from conversations.models import Conversation, Message

from .models import CoachbotFeedback, UsageLog


User = get_user_model()


def format_duration(total_seconds):
    """
    Convert a duration in seconds into readable text.

    Examples:
        42 -> "42 sec"
        125 -> "2 min 5 sec"
        3725 -> "1 hr 2 min 5 sec"
    """
    if total_seconds is None:
        return "0 sec"

    total_seconds = max(
        0,
        int(round(total_seconds)),
    )

    hours, remainder = divmod(
        total_seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    if hours:
        return (
            f"{hours} hr "
            f"{minutes} min "
            f"{seconds} sec"
        )

    if minutes:
        return (
            f"{minutes} min "
            f"{seconds} sec"
        )

    return f"{seconds} sec"


@staff_member_required
def admin_dashboard(request):
    # =========================================================
    # GENERAL PLATFORM STATISTICS
    # =========================================================

    usage_totals = UsageLog.objects.aggregate(
        total_input_chars=Sum("input_chars"),
        total_output_chars=Sum("output_chars"),
    )

    total_users = User.objects.count()
    total_conversations = Conversation.objects.count()
    total_messages = Message.objects.count()

    # =========================================================
    # SESSION-DURATION STATISTICS
    # =========================================================

    session_totals = Conversation.objects.aggregate(
        total_active_seconds=Sum(
            "active_seconds"
        ),
        average_active_seconds=Avg(
            "active_seconds",
            filter=Q(active_seconds__gt=0),
        ),
        tracked_session_count=Count(
            "id",
            filter=Q(active_seconds__gt=0),
        ),
        ended_session_count=Count(
            "id",
            filter=Q(
                session_ended_at__isnull=False
            ),
        ),
    )

    total_active_time = format_duration(
        session_totals[
            "total_active_seconds"
        ]
    )

    average_active_time = format_duration(
        session_totals[
            "average_active_seconds"
        ]
    )

    tracked_session_count = (
        session_totals[
            "tracked_session_count"
        ]
        or 0
    )

    ended_session_count = (
        session_totals[
            "ended_session_count"
        ]
        or 0
    )

    # =========================================================
    # USAGE BY COACHBOT AND MODEL
    # =========================================================

    usage_by_bot = (
        UsageLog.objects
        .values("chatbot__name")
        .annotate(
            total=Count("id"),
            conversation_count=Count(
                "conversation_id",
                distinct=True,
            ),
        )
        .order_by("-total")
    )

    usage_by_model = (
        UsageLog.objects
        .values("model__display_name")
        .annotate(
            total=Count("id"),
            conversation_count=Count(
                "conversation_id",
                distinct=True,
            ),
        )
        .order_by("-total")
    )

    recent_logs = (
        UsageLog.objects
        .select_related(
            "user",
            "chatbot",
            "model",
            "conversation",
        )
        .order_by("-created_at")[:25]
    )

    # =========================================================
    # REPEAT-USER CALCULATIONS FOR RECENT SESSIONS
    # =========================================================

    prior_user_conversations = (
        Conversation.objects
        .filter(
            user_id=OuterRef("user_id"),
            user_id__isnull=False,
            created_at__lt=OuterRef(
                "created_at"
            ),
            messages__role="user",
        )
        .exclude(
            pk=OuterRef("pk")
        )
        .values("user_id")
        .annotate(
            total=Count(
                "id",
                distinct=True,
            )
        )
        .values("total")[:1]
    )

    prior_guest_conversations = (
        Conversation.objects
        .filter(
            user__isnull=True,
            visitor_id=OuterRef(
                "visitor_id"
            ),
            created_at__lt=OuterRef(
                "created_at"
            ),
            messages__role="user",
        )
        .exclude(
            visitor_id=""
        )
        .exclude(
            pk=OuterRef("pk")
        )
        .values("visitor_id")
        .annotate(
            total=Count(
                "id",
                distinct=True,
            )
        )
        .values("total")[:1]
    )

    recent_session_objects = (
        Conversation.objects
        .select_related(
            "user",
            "chatbot",
            "model",
        )
        .annotate(
            prior_user_count=Coalesce(
                Subquery(
                    prior_user_conversations,
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
            prior_guest_count=Coalesce(
                Subquery(
                    prior_guest_conversations,
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
            user_message_count=Count(
                "messages",
                filter=Q(
                    messages__role="user"
                ),
                distinct=True,
            ),
        )
        .order_by("-created_at")[:25]
    )

    recent_sessions = []

    for session in recent_session_objects:
        if session.user_id:
            participant = (
                session.user.get_username()
            )

            previous_visit_count = (
                session.prior_user_count
                or 0
            )

        else:
            if session.guest_name:
                participant = (
                    f"Guest: "
                    f"{session.guest_name}"
                )
            else:
                participant = "Guest"

            if session.visitor_id:
                previous_visit_count = (
                    session.prior_guest_count
                    or 0
                )
            else:
                previous_visit_count = 0

        visit_number = (
            previous_visit_count + 1
        )

        recent_sessions.append(
            {
                "id": session.id,
                "title": session.title,
                "participant": participant,
                "chatbot": (
                    session.chatbot.name
                ),
                "framework": (
                    session.chatbot.framework
                ),
                "model": (
                    session.model.display_name
                    if session.model
                    else "Unknown model"
                ),
                "active_seconds": (
                    session.active_seconds
                    or 0
                ),
                "active_time": format_duration(
                    session.active_seconds
                ),
                "visit_number": visit_number,
                "is_repeat_user": (
                    previous_visit_count > 0
                ),
                "user_message_count": (
                    session.user_message_count
                    or 0
                ),
                "started_at": (
                    session.session_started_at
                ),
                "ended_at": (
                    session.session_ended_at
                ),
                "created_at": (
                    session.created_at
                ),
                "is_complete": (
                    session.session_ended_at
                    is not None
                ),
            }
        )

    # =========================================================
    # COACHBOT FEEDBACK STATISTICS
    # =========================================================

    overall = (
        CoachbotFeedback.objects
        .aggregate(
            response_count=Count("id"),
            average_usefulness=Avg(
                "usefulness"
            ),
            average_confidence=Avg(
                "confidence"
            ),
            average_session_duration=Avg(
                "session_duration_seconds"
            ),
            repeat_user_responses=Count(
                "id",
                filter=Q(
                    is_repeat_user=True
                ),
            ),
            first_time_user_responses=Count(
                "id",
                filter=Q(
                    is_repeat_user=False
                ),
            ),
        )
    )

    average_feedback_session_time = (
        format_duration(
            overall[
                "average_session_duration"
            ]
        )
    )

    summary_by_chatbot = (
        CoachbotFeedback.objects
        .values(
            "conversation__chatbot__id",
            "conversation__chatbot__name",
            "conversation__chatbot__framework",
        )
        .annotate(
            response_count=Count("id"),
            average_usefulness=Avg(
                "usefulness"
            ),
            average_confidence=Avg(
                "confidence"
            ),
            average_session_duration=Avg(
                "session_duration_seconds"
            ),
            repeat_user_responses=Count(
                "id",
                filter=Q(
                    is_repeat_user=True
                ),
            ),
        )
        .order_by("-response_count")
    )

    summary_by_chatbot_rows = []

    for row in summary_by_chatbot:
        summary_by_chatbot_rows.append(
            {
                **row,
                "average_session_time": (
                    format_duration(
                        row[
                            "average_session_duration"
                        ]
                    )
                ),
            }
        )

    recent_feedback = (
        CoachbotFeedback.objects
        .select_related(
            "conversation",
            "conversation__user",
            "conversation__chatbot",
            "conversation__model",
        )
        .order_by("-created_at")[:25]
    )

    # =========================================================
    # TEMPLATE CONTEXT
    # =========================================================

    context = {
        # General platform totals
        "total_users": total_users,
        "total_conversations": (
            total_conversations
        ),
        "total_messages": total_messages,

        "total_input_chars": (
            usage_totals[
                "total_input_chars"
            ]
            or 0
        ),
        "total_output_chars": (
            usage_totals[
                "total_output_chars"
            ]
            or 0
        ),

        # Session-duration statistics
        "total_active_time": (
            total_active_time
        ),
        "average_active_time": (
            average_active_time
        ),
        "tracked_session_count": (
            tracked_session_count
        ),
        "ended_session_count": (
            ended_session_count
        ),
        "recent_sessions": (
            recent_sessions
        ),

        # Message-level usage
        "usage_by_bot": usage_by_bot,
        "usage_by_model": usage_by_model,
        "recent_logs": recent_logs,

        # Feedback statistics
        "overall": overall,
        "average_feedback_session_time": (
            average_feedback_session_time
        ),
        "summary_by_chatbot": (
            summary_by_chatbot_rows
        ),
        "recent_feedback": (
            recent_feedback
        ),
    }

    return render(
        request,
        "analytics/admin_dashboard.html",
        context,
    )