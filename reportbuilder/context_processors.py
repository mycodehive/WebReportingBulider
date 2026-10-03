from django.db import OperationalError, ProgrammingError
from django.urls import reverse

from .models import CompanyBranding, MenuConfiguration


def company_branding(request):
    # Allow the login page to render while migrations are being installed.
    try:
        branding = CompanyBranding.objects.filter(pk=1).first()
    except (OperationalError, ProgrammingError):
        branding = None
    return {'company_branding': branding,
            'company_logo_url': f'{reverse("company_logo")}?v={branding.updated_at.timestamp()}' if branding and branding.logo else ''}


def workspace_navigation(request):
    defaults = [
        {'key': 'dashboard', 'label': '대시보드', 'order': 10},
        {'key': 'reports', 'label': '보고서 라이브러리', 'order': 20},
        {'key': 'connections', 'label': '데이터 연결', 'order': 30},
        {'key': 'boards', 'label': '게시판', 'order': 40},
        {'key': 'company', 'label': '회사 로고', 'order': 50},
        {'key': 'manual', 'label': '사용 가이드', 'order': 60},
        {'key': 'admin', 'label': '관리 설정', 'order': 70},
        {'key': 'menu_management', 'label': '메뉴관리', 'order': 80},
    ]
    routes = {
        'dashboard': '/',
        'reports': '/reports/',
        'connections': '/connections/',
        'boards': '/boards/',
        'company': '/settings/company/',
        'manual': '/manual/',
        'admin': '/admin/',
        'menu_management': '/menu-management/',
    }
    try:
        config = MenuConfiguration.objects.filter(pk=1).first()
        configured = config.items if config and isinstance(config.items, list) else defaults
    except (OperationalError, ProgrammingError):
        configured = defaults
    by_key = {item.get('key'): item for item in configured if isinstance(item, dict)}
    user = getattr(request, 'user', None)
    items = []
    for default in defaults:
        key = default['key']
        if key in {'company', 'admin', 'menu_management'} and not getattr(user, 'is_staff', False):
            continue
        item = {**default, **by_key.get(key, {})}
        item['url'] = routes[key]
        item['active'] = (request.path == '/' if key == 'dashboard' else request.path.startswith(routes[key]))
        items.append(item)
    items.sort(key=lambda item: (int(item.get('order', 0)), item['key']))
    return {'sidebar_items': items}
