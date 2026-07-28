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
        help_text="Open-ended feedback about how the CoachBot can improve.",
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