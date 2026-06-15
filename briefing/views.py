from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from briefing.models import Digest
from briefing.search import search_items


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    latest = Digest.objects.filter(status=Digest.Status.SENT).order_by("-period_end").first()
    return render(request, "briefing/dashboard.html", {"digest": latest})


@login_required
def archive(request: HttpRequest) -> HttpResponse:
    digests = Digest.objects.order_by("-period_end")
    return render(request, "briefing/archive.html", {"digests": digests})


@login_required
def digest_detail(request: HttpRequest, pk: int) -> HttpResponse:
    digest = get_object_or_404(Digest, pk=pk)
    return render(request, "briefing/digest_detail.html", {"digest": digest})


@login_required
def search(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    return render(request, "briefing/search.html", {"query": query, "results": search_items(query)})
