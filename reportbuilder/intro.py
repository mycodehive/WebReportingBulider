"""Public introduction, independent of the authenticated workspace layout."""
from django.shortcuts import render
from django.views.decorators.http import require_safe


@require_safe
def introduction(request):
    return render(request, "reportbuilder/intro/index.html")
