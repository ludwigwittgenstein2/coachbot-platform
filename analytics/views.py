from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Sum
from django.shortcuts import render

from conversations.models import Conversation, Message
from analytics.models import CoachbotFeedback, UsageLog


User = get_user_model()


@staff_member_required
def admin_dashboard(request):
    # -----------------------------------
    # General platform statistics
    # -----------------------------------
    usage_totals = UsageLog.objects.aggregate(
        total_input_chars=Sum("input_chars"),
        total_output_chars=Sum("output_chars"),
    )

    usage_by_bot = (
        UsageLog.objects
        .values("chatbot__name")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    usage_by_model = (
        UsageLog.objects
        .values("model__display_name")
        .annotate(total=Count("id"))
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

    # -----------------------------------
    # CoachBot feedback statistics
    # -----------------------------------
    overall = CoachbotFeedback.objects.aggregate(
        response_count=Count("id"),
        average_usefulness=Avg("usefulness"),
        average_confidence=Avg("confidence"),
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
            average_usefulness=Avg("usefulness"),
            average_confidence=Avg("confidence"),
        )
        .order_by("-response_count")
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

    context = {
        # General platform totals
        "total_users": User.objects.count(),
        "total_conversations": Conversation.objects.count(),
        "total_messages": Message.objects.count(),

        "total_input_chars": (
            usage_totals["total_input_chars"] or 0
        ),
        "total_output_chars": (
            usage_totals["total_output_chars"] or 0
        ),

        # Usage details
        "usage_by_bot": usage_by_bot,
        "usage_by_model": usage_by_model,
        "recent_logs": recent_logs,

        # Feedback details
        "overall": overall,
        "summary_by_chatbot": summary_by_chatbot,
        "recent_feedback": recent_feedback,
    }

    return render(
        request,
        "analytics/admin_dashboard.html",
        context,
    )