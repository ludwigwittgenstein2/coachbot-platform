from django.contrib import admin
from .models import Chatbot, OllamaModel

@admin.register(Chatbot)
class ChatbotAdmin(admin.ModelAdmin):
    list_display = ('name', 'framework', 'is_active')
    search_fields = ('name', 'framework')

@admin.register(OllamaModel)
class OllamaModelAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'name', 'is_active')
