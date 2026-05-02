from django.conf import settings
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

    guest_name = models.CharField(max_length=150, blank=True)

    chatbot = models.ForeignKey(Chatbot, on_delete=models.PROTECT)

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