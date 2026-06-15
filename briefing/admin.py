from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from briefing.models import Digest, Item, Source, Theme
from briefing.tasks import poll_source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("kind", "config", "enabled", "last_polled_at")
    actions = ["poll_now"]

    @admin.action(description="Poll selected sources now")
    def poll_now(self, request: HttpRequest | None, queryset: QuerySet[Source]) -> None:
        for source in queryset:
            poll_source.delay(source.id)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "summarised_at", "summarise_failed")
    list_filter = ("source", "summarise_failed")


@admin.register(Digest)
class DigestAdmin(admin.ModelAdmin):
    list_display = ("kind", "period_start", "period_end", "status")


admin.site.register(Theme)
