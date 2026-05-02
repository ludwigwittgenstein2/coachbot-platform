from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Count, Sum
from django.shortcuts import render
from conversations.models import Conversation, Message
from analytics.models import UsageLog

@staff_member_required
def admin_dashboard(request):
    usage_by_bot = UsageLog.objects.values('chatbot__name').annotate(total=Count('id')).order_by('-total')
    usage_by_model = UsageLog.objects.values('model__display_name').annotate(total=Count('id')).order_by('-total')
    return render(request, 'analytics/admin_dashboard.html', {
        'total_users': User.objects.count(),
        'total_conversations': Conversation.objects.count(),
        'total_messages': Message.objects.count(),
        'total_input_chars': UsageLog.objects.aggregate(Sum('input_chars'))['input_chars__sum'] or 0,
        'total_output_chars': UsageLog.objects.aggregate(Sum('output_chars'))['output_chars__sum'] or 0,
        'usage_by_bot': usage_by_bot,
        'usage_by_model': usage_by_model,
        'recent_logs': UsageLog.objects.select_related('user', 'chatbot', 'model').order_by('-created_at')[:25]
    })
