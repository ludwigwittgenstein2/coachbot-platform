from django.urls import path
from . import views
urlpatterns = [
    path('start/', views.start_chat, name='start_chat'),
    path('dashboard/', views.my_dashboard, name='my_dashboard'),
    path('<int:conversation_id>/', views.chat_detail, name='chat_detail'),
    path('<int:conversation_id>/send/', views.send_message, name='send_message'),
]
