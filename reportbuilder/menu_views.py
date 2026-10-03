from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .community_models import MenuConfiguration, default_menu_items


@login_required
@require_http_methods(['GET', 'POST'])
def menu_management(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('메뉴 관리는 전체 관리자만 이용할 수 있습니다.')

    defaults = default_menu_items()
    config = MenuConfiguration.objects.filter(pk=1).first()
    configured = config.items if config and isinstance(config.items, list) else defaults
    by_key = {item.get('key'): item for item in configured if isinstance(item, dict)}
    items = [{**default, **by_key.get(default['key'], {})} for default in defaults]

    if request.method == 'POST':
        keys = request.POST.getlist('keys')
        labels = request.POST.getlist('labels')
        orders = request.POST.getlist('orders')
        if not (len(keys) == len(labels) == len(orders) == len(defaults)) or set(keys) != {item['key'] for item in defaults}:
            messages.error(request, '메뉴 항목이 올바르지 않습니다. 페이지를 새로고침한 뒤 다시 저장해 주세요.')
        else:
            submitted = []
            valid = True
            for key, label, order in zip(keys, labels, orders):
                label = label.strip()
                if not label or len(label) > 40 or not order.lstrip('-').isdigit():
                    valid = False
                    break
                submitted.append({'key': key, 'label': label, 'order': int(order)})
            if not valid:
                messages.error(request, '메뉴명은 1~40자, 순서는 정수로 입력해 주세요.')
            else:
                config, _ = MenuConfiguration.objects.get_or_create(pk=1)
                config.items = submitted
                config.save(update_fields=['items', 'updated_at'])
                messages.success(request, '좌측 메뉴명과 순서를 저장했습니다.')
                return redirect('menu_management')
    items.sort(key=lambda item: (int(item.get('order', 0)), item['key']))
    return render(request, 'reportbuilder/menu_management.html', {'items': items})
