from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.contrib.auth.models import User

from bots.models import Chatbot, OllamaModel
from conversations.models import Conversation, Message
from analytics.models import UsageLog


@staff_member_required
def admin_dashboard(request):
    context = {
        "total_users": User.objects.count(),
        "total_conversations": Conversation.objects.count(),
        "total_messages": Message.objects.count(),
        "total_usage_logs": UsageLog.objects.count(),
        "bots": Chatbot.objects.all(),
        "models": OllamaModel.objects.all(),
        "recent_conversations": Conversation.objects.order_by("-created_at")[:20],
    }

    return render(request, "analytics/admin_dashboard.html", context)