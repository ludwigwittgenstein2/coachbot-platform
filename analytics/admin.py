from django.contrib import admin
from .models import UsageLog

@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'chatbot', 'model', 'input_chars', 'output_chars', 'created_at')
    list_filter = ('chatbot', 'model', 'created_at')
