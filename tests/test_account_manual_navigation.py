import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from reportbuilder.models import Connection, ManualVersion, Report, WorkspaceMenu

pytestmark = pytest.mark.django_db


def test_signup_creates_account_and_private_demo_report(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    login_page = client.get(reverse("login"))
    assert "회원가입".encode() in login_page.content
    response = client.post(reverse("signup"), {
        "username": "new-member",
        "email": "new-member@example.com",
        "password1": "Distinctive!BlueRiver2026",
        "password2": "Distinctive!BlueRiver2026",
    })
    assert response.status_code == 302
    user = get_user_model().objects.get(username="new-member")
    assert user.email == "new-member@example.com"
    report = Report.objects.get(owner=user, name="매출 현황 예제")
    assert report.bindings
    connection = Connection.objects.get(name="합성 매출 CSV", owner=user)
    assert str(connection.pk) == report.bindings[0]["connection_id"]
    assert "_auth_user_id" in client.session


def test_signup_rejects_password_mismatch_and_duplicate_email(client):
    response = client.post(reverse("signup"), {
        "username": "mismatch", "email": "mismatch@example.com",
        "password1": "Distinctive!BlueRiver2026", "password2": "Different!BlueRiver2026",
    })
    assert response.status_code == 200
    assert not get_user_model().objects.filter(username="mismatch").exists()
    get_user_model().objects.create_user("existing", email="same@example.com", password="Distinctive!BlueRiver2026")
    response = client.post(reverse("signup"), {
        "username": "duplicate-email", "email": "SAME@example.com",
        "password1": "Distinctive!BlueRiver2026", "password2": "Distinctive!BlueRiver2026",
    })
    assert response.status_code == 200
    assert not get_user_model().objects.filter(username="duplicate-email").exists()


def test_manual_published_versions_are_audience_specific(client):
    user = get_user_model().objects.create_user("member", password="Distinctive!BlueRiver2026")
    staff = get_user_model().objects.create_user("staff", password="Distinctive!BlueRiver2026", is_staff=True)
    ManualVersion.objects.create(audience="user", version="1.0", content="# User Manual", is_published=False)
    ManualVersion.objects.create(audience="user", version="2.0", content="# Published User Manual", is_published=True)
    ManualVersion.objects.create(audience="admin", version="5.0", content="# Published Admin Manual", is_published=True)

    client.force_login(user)
    page = client.get(reverse("manual")).content.decode()
    assert "공개 버전 2.0" in page
    assert "Published User Manual" in page
    assert "Published Admin Manual" not in page

    client.force_login(staff)
    page = client.get(reverse("manual")).content.decode()
    assert "관리자용 매뉴얼" in page
    assert "공개 버전 5.0" in page
    assert "Published Admin Manual" in page


def test_admin_can_rebuild_selected_users_demo_and_explain_menus(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    admin_user = get_user_model().objects.create_superuser("root", "root@example.com", "Distinctive!BlueRiver2026")
    user = get_user_model().objects.create_user("legacy-user", email="legacy@example.com", password="Distinctive!BlueRiver2026")
    call_command("seed_demo", user_id=str(user.pk))
    previous = Report.objects.get(owner=user, name="매출 현황 예제").pk

    client.force_login(admin_user)
    response = client.post(reverse("admin:auth_user_changelist"), {
        "action": "generate_demo_reports",
        "_selected_action": str(user.pk),
    })
    assert response.status_code == 302
    assert Report.objects.filter(owner=user, name="매출 현황 예제").count() == 1
    assert Report.objects.get(owner=user, name="매출 현황 예제").pk != previous

    page = client.get(reverse("admin:reportbuilder_connection_changelist"))
    assert page.status_code == 200
    html = page.content.decode()
    assert html.index('id="content-main"') < html.index("이 메뉴의 역할")
    assert "보고서 데이터셋" in html
    assert "reportbuilder/admin.css" in html

    menus = client.get(reverse("admin:reportbuilder_workspacemenu_changelist"))
    assert menus.status_code == 200
    assert WorkspaceMenu.objects.filter(key="manual").exists()
