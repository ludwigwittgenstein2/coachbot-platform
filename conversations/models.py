from django.conf import settings
from django.db import models

from bots.models import Chatbot, OllamaModel


class Conversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
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

    title = models.CharField(max_length=200, default="New conversation")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        if self.user:
            return f"{self.title} - {self.user}"
        return f"{self.title} - Guest: {self.guest_name}"


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
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    model_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]