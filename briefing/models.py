from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class Source(models.Model):
    class Kind(models.TextChoices):
        RSS = "rss", "RSS/Atom"
        READWISE = "readwise", "Readwise Reader"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    config = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.config.get('url', self.pk)}"


class Item(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="items")
    external_id = models.CharField(max_length=512)
    url = models.URLField(max_length=1024)
    title = models.CharField(max_length=512, blank=True)
    author = models.CharField(max_length=256, blank=True)
    raw_content = models.TextField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    content_hash = models.CharField(max_length=64)
    summary = models.TextField(blank=True)
    summarised_at = models.DateTimeField(null=True, blank=True)
    summarise_failed = models.BooleanField(default=False)
    search_vector = SearchVectorField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"], name="uniq_source_external_id"
            ),
        ]
        indexes = [GinIndex(fields=["search_vector"], name="item_search_gin")]

    def __str__(self) -> str:
        return self.title or self.url


class Digest(models.Model):
    class Kind(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        SENT = "sent", "Sent"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "period_start", "period_end"], name="uniq_digest_kind_period"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.period_start:%Y-%m-%d}"


class Theme(models.Model):
    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="themes")
    title = models.CharField(max_length=256)
    narrative = models.TextField()
    importance = models.IntegerField(default=0)

    class Meta:
        ordering = ["-importance"]

    def __str__(self) -> str:
        return self.title


class ThemeItem(models.Model):
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="theme_items")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="theme_items")
    rationale = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.theme_id} ↔ {self.item_id}"
