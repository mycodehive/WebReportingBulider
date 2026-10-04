from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from .community_models import MenuConfiguration, default_menu_items
from .models import WorkspaceMenu
from .settings_forms import SectionFormSet, SettingsMenuFormSet
from .settings_navigation import settings_navigation


def valid_internal_url(value):
    value = value.strip()
    parsed = urlsplit(value)
    return value.startswith("/") and not value.startswith("//") and not parsed.scheme and not parsed.netloc and "\\" not in value


def unique_menu_key(label):
    base = slugify(label, allow_unicode=False) or "custom-menu"
    base = base[:50]
    key = base
    suffix = 2
    while WorkspaceMenu.objects.filter(key=key).exists():
        ending = f"-{suffix}"
        key = f"{base[:50 - len(ending)]}{ending}"
        suffix += 1
    return key


@login_required
@require_http_methods(["GET", "POST"])
def menu_management(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("메뉴 관리는 전체 관리자만 이용할 수 있습니다.")

    action = request.POST.get("action", "save") if request.method == "POST" else None
    section_forms = SectionFormSet(request.POST if action == "save_settings_sections" else None, prefix="sections")
    settings_menu_forms = SettingsMenuFormSet(request.POST if action == "save_settings_children" else None, prefix="children")
    if action in {"save_settings_sections", "save_settings_children"}:
        forms = section_forms if action == "save_settings_sections" else settings_menu_forms
        if forms.is_valid():
            with transaction.atomic():
                forms.save()
            messages.success(request, "환경설정 메뉴를 저장했습니다.")
            return redirect("menu_management")
        messages.error(request, "환경설정 메뉴 입력값을 확인해 주세요.")
        return render(request, "reportbuilder/menu_management.html", {
            "items": WorkspaceMenu.objects.all(), "section_forms": section_forms,
            "settings_menu_forms": settings_menu_forms, **settings_navigation("site", "menus", request),
        })

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "create":
            label = request.POST.get("new_label", "").strip()
            url = request.POST.get("new_url", "").strip()
            try:
                order = int(request.POST.get("new_order", "0"))
                if not label or len(label) > 40:
                    raise ValidationError("메뉴명은 1~40자로 입력해 주세요.")
                if not valid_internal_url(url):
                    raise ValidationError("주소는 사이트 내부 경로(/로 시작)만 등록할 수 있습니다.")
                menu = WorkspaceMenu(
                    key=unique_menu_key(label), label=label, url=url, order=order,
                    staff_only=request.POST.get("new_staff_only") == "on",
                    active=request.POST.get("new_active") == "on",
                )
                menu.full_clean()
                menu.save()
                messages.success(request, f"'{menu.label}' 메뉴를 추가했습니다.")
            except (ValueError, ValidationError) as exc:
                messages.error(request, str(exc))
            return redirect("menu_management")

        menus = list(WorkspaceMenu.objects.all())
        if action == "delete_selected":
            ids = request.POST.getlist("delete_ids")
            deleted, _ = WorkspaceMenu.objects.filter(pk__in=ids).delete()
            messages.success(request, f"메뉴 {deleted}개를 삭제했습니다.")
            return redirect("menu_management")

        try:
            with transaction.atomic():
                # Preserve the former form payload for clients using the old title/order editor.
                if request.POST.getlist("keys"):
                    keys = request.POST.getlist("keys")
                    labels = request.POST.getlist("labels")
                    orders = request.POST.getlist("orders")
                    expected_keys = {item['key'] for item in default_menu_items()}
                    legacy_keys = (expected_keys - {'settings'}) | {'company', 'menu_management'}
                    if not (len(keys) == len(labels) == len(orders) == len(set(keys))
                            and set(keys) in (expected_keys, legacy_keys)):
                        raise ValidationError("메뉴 항목이 올바르지 않습니다.")
                    submitted = []
                    for key, label, order in zip(keys, labels, orders):
                        # Old clients can still submit the former separate settings entries.
                        if key in {'company', 'menu_management'}:
                            if key == 'menu_management':
                                continue
                            key = 'settings'
                            label = '환경설정'
                        menu = WorkspaceMenu.objects.get(key=key)
                        menu.label = label.strip()
                        menu.order = int(order)
                        menu.full_clean()
                        menu.save()
                        submitted.append({"key": key, "label": menu.label, "order": menu.order})
                    legacy_config, _ = MenuConfiguration.objects.get_or_create(pk=1)
                    legacy_config.items = submitted
                    legacy_config.save(update_fields=["items", "updated_at"])
                else:
                    active_ids = set(request.POST.getlist("active_ids"))
                    staff_ids = set(request.POST.getlist("staff_ids"))
                    for menu in menus:
                        label = request.POST.get(f"label_{menu.pk}", "").strip()
                        url = request.POST.get(f"url_{menu.pk}", "").strip()
                        if not label or len(label) > 40 or not valid_internal_url(url):
                            raise ValidationError(f"'{menu.label}' 메뉴명 또는 내부 주소를 확인해 주세요.")
                        menu.label = label
                        menu.url = url
                        menu.order = int(request.POST.get(f"order_{menu.pk}", "0"))
                        menu.staff_only = str(menu.pk) in staff_ids
                        menu.active = str(menu.pk) in active_ids
                        menu.full_clean()
                        menu.save()
            messages.success(request, "메뉴 설정을 저장했습니다.")
        except (ValueError, WorkspaceMenu.DoesNotExist, ValidationError) as exc:
            messages.error(request, str(exc))
        return redirect("menu_management")

    items = WorkspaceMenu.objects.all()
    return render(request, "reportbuilder/menu_management.html", {"items": items, "section_forms": section_forms, "settings_menu_forms": settings_menu_forms,
                                                                  **settings_navigation("site", "menus", request)})
