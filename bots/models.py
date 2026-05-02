from django.db import models

class Chatbot(models.Model):
    name = models.CharField(max_length=120, unique=True)
    framework = models.CharField(max_length=80)
    description = models.TextField()
    system_prompt = models.TextField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class OllamaModel(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.display_name
