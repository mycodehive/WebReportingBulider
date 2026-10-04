import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection

from reportbuilder.models import ManualVersion


@pytest.mark.django_db
def test_infographics_manual_publishes_both_audiences_and_preserves_custom_text(client):
    old = ManualVersion.objects.create(audience='user', version='custom-user', content='# 사용자 맞춤 내용', is_published=True)
    ManualVersion.objects.create(audience='admin', version='custom-admin', content='# 관리자 맞춤 내용', is_published=True)
    draft = ManualVersion.objects.create(audience='user', version='draft', content='# 비공개 초안', is_published=False)
    ManualVersion.objects.filter(version='infographics-20261004').delete()
    migration = importlib.import_module('reportbuilder.migrations.0016_infographics_manual')
    migration.publish_infographics_manual(apps, SimpleNamespace(connection=connection))
    migration.publish_infographics_manual(apps, SimpleNamespace(connection=connection))
    assert ManualVersion.objects.filter(version='infographics-20261004').count() == 2
    old.refresh_from_db()
    draft.refresh_from_db()
    assert old.content == '# 사용자 맞춤 내용' and draft.content == '# 비공개 초안' and not draft.is_published
    for staff in (False, True):
        user = get_user_model().objects.create_user(f'manual-chart-{staff}', is_staff=staff)
        client.force_login(user)
        html = client.get('/manual/').content.decode()
        assert '숫자변환' in html and '차트 이미지와 갱신' in html
        assert ('관리자 운영 점검' in html) == staff
        assert ('관리자 맞춤 내용' if staff else '사용자 맞춤 내용') in html
