from django.contrib import admin

from .models import CoachbotFeedback, UsageLog


@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "participant",
        "chatbot",
        "model",
        "input_chars",
        "output_chars",
        "created_at",
    )

    list_filter = (
        "chatbot",
        "model",
        "created_at",
    )

    search_fields = (
        "user__username",
        "user__email",
        "guest_name",
        "chatbot__name",
        "model__name",
    )

    list_select_related = (
        "user",
        "chatbot",
        "model",
        "conversation",
    )

    @admin.display(description="Participant")
    def participant(self, obj):
        if obj.user:
            return obj.user.username

        return obj.guest_name or "Guest"


@admin.register(CoachbotFeedback)
class CoachbotFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "participant",
        "chatbot_name",
        "framework",
        "usefulness",
        "confidence",
        "created_at",
    )

    list_filter = (
        "usefulness",
        "confidence",
        "conversation__chatbot",
        "conversation__chatbot__framework",
        "created_at",
    )

    search_fields = (
        "conversation__user__username",
        "conversation__user__email",
        "conversation__guest_name",
        "conversation__chatbot__name",
        "improvement_feedback",
    )

    readonly_fields = (
        "conversation",
        "participant",
        "chatbot_name",
        "framework",
        "usefulness",
        "confidence",
        "improvement_feedback",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "conversation",
        "conversation__user",
        "conversation__chatbot",
        "conversation__model",
    )

    @admin.display(description="Participant")
    def participant(self, obj):
        return obj.participant_name

    @admin.display(description="CoachBot")
    def chatbot_name(self, obj):
        return obj.conversation.chatbot.name

    @admin.display(description="Framework")
    def framework(self, obj):
        return obj.conversation.chatbot.framework