from django.urls import path

from briefing import views

app_name = "briefing"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("archive/", views.archive, name="archive"),
    path("digest/<int:pk>/", views.digest_detail, name="digest_detail"),
    path("search/", views.search, name="search"),
]
