from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from conversations.views import guest_name, register, guest_logout

def home(request):
    return render(request, "home.html")


def how_to_use(request):
    return render(request, "how_to_use.html")


urlpatterns = [
    path("", home, name="home"),
    path("how-to-use/", how_to_use, name="how_to_use"),
    path("guest-name/", guest_name, name="guest_name"),
    path("register/", register, name="register"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),

    path("bots/", include("bots.urls")),
    path("chat/", include("conversations.urls")),
    path("analytics/", include("analytics.urls")),
    path("guest-logout/", guest_logout, name="guest_logout"),
]