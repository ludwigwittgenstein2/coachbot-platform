from django.conf import settings
from django.db import models
from django.utils import timezone

from bots.models import Chatbot, OllamaModel


class Conversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    guest_name = models.CharField(
        max_length=150,
        blank=True,
    )

    # Random browser/session identifier used to recognize repeat guests.
    # Authenticated repeat users are identified through the user field.
    visitor_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text=(
            "Anonymous browser identifier used to recognize "
            "repeat guest users."
        ),
    )

    chatbot = models.ForeignKey(
        Chatbot,
        on_delete=models.PROTECT,
    )

    model = models.ForeignKey(
        OllamaModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    title = models.CharField(
        max_length=200,
        default="New conversation",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # Session-use tracking
    session_started_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        help_text="Time the CoachBot session began.",
    )

    session_ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Time the participant ended the CoachBot session.",
    )

    active_seconds = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Approximate active time spent using this conversation, "
            "measured in seconds."
        ),
    )

    last_activity_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Most recent recorded active-use heartbeat.",
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        if self.user:
            return f"{self.title} - {self.user}"

        return f"{self.title} - Guest: {self.guest_name}"

    @property
    def participant_name(self):
        if self.user:
            return self.user.username

        return self.guest_name or "Guest"

    @property
    def session_duration_display(self):
        """
        Return active session duration in a readable format.
        """
        total_seconds = self.active_seconds or 0

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"{hours} hr {minutes} min {seconds} sec"

        if minutes:
            return f"{minutes} min {seconds} sec"

        return f"{seconds} sec"

    @property
    def is_session_complete(self):
        return self.session_ended_at is not None


class Message(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        related_name="messages",
        on_delete=models.CASCADE,
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
    )

    content = models.TextField()

    model_name = models.CharField(
        max_length=100,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        preview = self.content[:60]

        return (
            f"{self.get_role_display()} message "
            f"in conversation {self.conversation_id}: {preview}"
        )