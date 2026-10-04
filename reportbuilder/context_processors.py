from django.db import OperationalError, ProgrammingError
from django.urls import reverse

from .models import CompanyBranding, WorkspaceMenu


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
        {'key': 'dashboard', 'label': '대시보드', 'order': 10, 'url': '/'},
        {'key': 'reports', 'label': '보고서 라이브러리', 'order': 20, 'url': '/reports/'},
        {'key': 'connections', 'label': '데이터 연결', 'order': 30, 'url': '/connections/'},
        {'key': 'boards', 'label': '게시판', 'order': 40, 'url': '/boards/'},
        {'key': 'settings', 'label': '환경설정', 'order': 50, 'url': '/settings/', 'staff_only': True},
        {'key': 'manual', 'label': '사용 가이드', 'order': 60, 'url': '/manual/'},
        {'key': 'admin', 'label': '관리 설정', 'order': 70, 'url': '/admin/', 'staff_only': True},
    ]
    user = getattr(request, 'user', None)
    try:
        configured = list(WorkspaceMenu.objects.filter(active=True).order_by('order', 'label', 'key'))
    except (OperationalError, ProgrammingError):
        configured = []
    if configured:
        items = [
            {'key': menu.key, 'label': menu.label, 'order': menu.order, 'url': menu.url,
             'active': request.path == menu.url or (menu.url != '/' and request.path.startswith(menu.url.rstrip('/') + '/'))}
            for menu in configured if not menu.staff_only or getattr(user, 'is_staff', False)
        ]
    else:
        items = [
            {**item, 'active': request.path == item['url'] if item['url'] == '/' else
             (request.path == item['url'] or request.path.startswith(item['url'].rstrip('/') + '/'))}
            for item in defaults if not item.get('staff_only') or getattr(user, 'is_staff', False)
        ]
    for item in items:
        if item['key'] == 'settings':
            item['active'] = item['active'] or request.path in {
                reverse('workspace_settings'), reverse('company_settings'), reverse('menu_management'),
            }
    return {'sidebar_items': items}
