from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from bots.models import Chatbot, OllamaModel
from conversations.models import Conversation


class UsageLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    guest_name = models.CharField(
        max_length=150,
        blank=True,
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

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
    )

    input_chars = models.IntegerField(default=0)
    output_chars = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.user:
            return f"{self.user} - {self.chatbot.name}"

        return f"Guest: {self.guest_name} - {self.chatbot.name}"


class CoachbotFeedback(models.Model):
    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.CASCADE,
        related_name="feedback",
    )

    usefulness = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
        help_text="1 = Not useful, 5 = Extremely useful",
    )

    confidence = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
        help_text="1 = Not confident, 5 = Extremely confident",
    )

    improvement_feedback = models.TextField(
        blank=True,
        max_length=5000,
        help_text=(
            "Open-ended feedback about how the CoachBot can improve."
        ),
    )

    session_duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Approximate active time spent using the CoachBot, "
            "measured in seconds."
        ),
    )

    is_repeat_user = models.BooleanField(
        null=True,
        blank=True,
        help_text=(
            "Whether the participant had a prior CoachBot conversation."
        ),
    )

    visit_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "The participant's conversation number across the application."
        ),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "CoachBot feedback"
        verbose_name_plural = "CoachBot feedback"

    def __str__(self):
        return (
            f"Conversation {self.conversation_id}: "
            f"usefulness={self.usefulness}, "
            f"confidence={self.confidence}"
        )

    @property
    def participant_name(self):
        if self.conversation.user:
            return self.conversation.user.username

        return self.conversation.guest_name or "Guest"

    @property
    def session_duration_display(self):
        """
        Convert the recorded session duration into readable text.
        """
        total_seconds = self.session_duration_seconds

        if total_seconds is None:
            return "Unknown"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"{hours} hr {minutes} min {seconds} sec"

        if minutes:
            return f"{minutes} min {seconds} sec"

        return f"{seconds} sec"

    @property
    def repeat_user_display(self):
        if self.is_repeat_user is None:
            return "Unknown"

        return "Yes" if self.is_repeat_user else "No"