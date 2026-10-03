import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from reportbuilder.community_forms import BoardForm, clean_html
from reportbuilder.models import Board, BoardCategory, BoardPost, BoardReply, BoardStatus, CompanyBranding

pytestmark = pytest.mark.django_db


@pytest.fixture
def community():
    users = {name: get_user_model().objects.create_user(name, password='testpassword', is_staff=name == 'admin')
             for name in ['admin', 'manager', 'operator', 'alice', 'bob']}
    board = Board.objects.create(name='1:1 문의', kind='qa')
    board.managers.add(users['manager'])
    board.operators.add(users['operator'])
    statuses = [BoardStatus.objects.create(board=board, name=name, color=color, order=i)
                for i, (name, color) in enumerate([('접수', '#2563eb'), ('보류', '#b45309'), ('완료', '#15803d')])]
    posts = {name: BoardPost.objects.create(board=board, author=users[name], title=f'{name} private', body=f'<p>{name} secret</p>', status=statuses[0])
             for name in ['alice', 'bob']}
    return users, board, statuses, posts


def url(name, board, post=None, **kwargs):
    kwargs['board_id'] = board.pk
    if post:
        kwargs['post_id'] = post.pk
    return reverse(name, kwargs=kwargs)


@pytest.mark.parametrize('role', ['alice', 'bob', 'manager', 'operator', 'admin'])
def test_private_visibility_and_direct_access(client, community, role):
    users, board, _, posts = community
    client.force_login(users[role])
    privileged = role in ['manager', 'operator', 'admin']
    response = client.get(url('board_list', board))
    assert response.status_code == 200
    assert 'no-store' in response['Cache-Control']
    for author, post in posts.items():
        allowed = privileged or author == role
        assert (post.title in response.content.decode()) == allowed
        assert client.get(url('board_post', board, post)).status_code == (200 if allowed else 404)
        if not allowed:
            for endpoint in ['board_post_edit', 'board_post_delete', 'board_post_status', 'board_post']:
                assert client.post(url(endpoint, board, post), {'body': 'attempt'}).status_code == 404
    filtered = client.get(url('board_list', board), {'q': 'bob secret'})
    assert ('bob private' in filtered.content.decode()) == (privileged or role == 'bob')
    index = client.get(reverse('board_index'))
    assert index.context['boards'][0].visible_count == (2 if privileged else 1)


def test_board_role_boundaries_and_hidden_boards(client, community):
    users, board, _, _ = community
    for role in ['operator', 'alice']:
        client.force_login(users[role])
        assert client.get(url('board_settings', board)).status_code == 403
        assert client.get(url('board_taxonomy', board)).status_code == 403
        assert client.post(url('board_delete', board)).status_code == 403
        assert client.get(reverse('board_create')).status_code == 403
    client.force_login(users['manager'])
    assert client.get(url('board_settings', board)).status_code == 200
    board.active = False
    board.save()
    client.force_login(users['alice'])
    assert client.get(url('board_list', board)).status_code == 404
    assert client.get(reverse('board_index')).context['boards'] == []
    client.force_login(users['operator'])
    assert client.get(url('board_list', board)).status_code == 200


def test_post_create_edit_reply_and_status(client, community):
    users, board, statuses, posts = community
    foreign = Board.objects.create(name='other', kind='qa')
    foreign_category = BoardCategory.objects.create(board=foreign, name='private category')
    foreign_status = BoardStatus.objects.create(board=foreign, name='other')
    client.force_login(users['alice'])
    response = client.post(url('board_post_create', board), {'title': 'new', 'body': '<p>Hello</p><img src=x onerror=alert(1)>', 'pinned': 'on', 'status': statuses[2].pk})
    assert response.status_code == 302
    post = BoardPost.objects.get(title='new')
    assert post.author == users['alice'] and post.status == statuses[0] and not post.pinned
    assert 'onerror' not in post.body
    response = client.post(url('board_post_edit', board, post), {'title': 'new', 'body': 'edited', 'category': foreign_category.pk})
    assert response.status_code == 200
    assert response.context['form'].errors
    assert client.post(url('board_post_status', board, post), {'status': statuses[2].pk}).status_code == 403
    client.force_login(users['operator'])
    assert client.post(url('board_post_status', board, post), {'status': foreign_status.pk}).status_code == 302
    post.refresh_from_db()
    assert post.status == statuses[0]
    client.post(url('board_post_status', board, post), {'status': statuses[2].pk})
    post.refresh_from_db()
    assert post.status == statuses[2]
    assert client.post(url('board_post', board, post), {'body': '<p>answer</p>'}).status_code == 302
    reply = post.replies.get()
    client.force_login(users['bob'])
    assert client.get(url('board_reply_edit', board, post, reply_id=reply.pk)).status_code == 404
    client.force_login(users['alice'])
    assert client.get(url('board_reply_edit', board, post, reply_id=reply.pk)).status_code == 403
    client.force_login(users['operator'])
    assert client.post(url('board_reply_edit', board, post, reply_id=reply.pk), {'body': '<p>updated answer</p>'}).status_code == 302
    reply.refresh_from_db()
    assert 'updated answer' in reply.body
    client.post(url('board_reply_edit', board, post, reply_id=reply.pk), {'action': 'delete'})
    assert not BoardReply.objects.filter(pk=reply.pk).exists()
    client.force_login(users['alice'])
    client.post(url('board_post_delete', board, post))
    assert not BoardPost.objects.filter(pk=post.pk).exists()


def test_private_type_cannot_be_made_public(community):
    _, board, _, _ = community
    form = BoardForm({'name': board.name, 'kind': 'list', 'active': 'on'}, instance=board)
    assert not form.is_valid()
    assert 'kind' in form.errors


@pytest.mark.parametrize('kind', ['list', 'card', 'qa'])
def test_board_create_and_delete(client, community, kind):
    users, _, _, _ = community
    client.force_login(users['admin'])
    response = client.post(reverse('board_create'), {'name': f'board {kind}', 'kind': kind, 'active': 'on', 'allow_user_posts': 'on', 'operators': [users['operator'].pk]})
    assert response.status_code == 302
    board = Board.objects.get(name=f'board {kind}')
    assert list(board.statuses.values_list('name', flat=True)) == ['접수', '보류', '완료']
    client.force_login(users['alice'])
    assert client.get(url('board_list', board)).status_code == 200
    assert client.get(url('board_post_create', board)).status_code == 200
    board.allow_user_posts = False
    board.save()
    assert client.post(url('board_post_create', board), {'title': 'blocked', 'body': 'hello'}).status_code == 403
    client.force_login(users['admin'])
    assert client.get(url('board_delete', board)).status_code == 200
    assert client.post(url('board_delete', board)).status_code == 302
    assert not Board.objects.filter(pk=board.pk).exists()


def test_taxonomy_create_delete_and_color_validation(client, community):
    users, board, statuses, posts = community
    client.force_login(users['manager'])
    data = {'categories-TOTAL_FORMS': '1', 'categories-INITIAL_FORMS': '0', 'categories-0-name': '기술문의', 'categories-0-order': '0',
            'statuses-TOTAL_FORMS': '4', 'statuses-INITIAL_FORMS': '3'}
    for i, status in enumerate(statuses):
        data.update({f'statuses-{i}-id': status.pk, f'statuses-{i}-name': status.name, f'statuses-{i}-color': status.color, f'statuses-{i}-order': i})
    data.update({'statuses-0-DELETE': 'on', 'statuses-3-name': '검토중', 'statuses-3-color': '#8040ff', 'statuses-3-order': '3'})
    response = client.post(url('board_taxonomy', board), data)
    assert response.status_code == 302
    assert board.categories.get().name == '기술문의'
    assert list(board.statuses.values_list('name', flat=True)) == ['보류', '완료', '검토중']
    posts['alice'].refresh_from_db()
    assert posts['alice'].status.name == '보류'
    bad = BoardStatus(board=board, name='bad', color='red; background:url(x)')
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        bad.full_clean()


def test_html_sanitization():
    result = clean_html('<p style="color:red;background-image:url(javascript:x)" onclick="x()">text<a href="javascript:alert(1)">link</a></p><svg onload="x()"></svg><iframe src="x"></iframe><form><button formaction="javascript:x">x</button></form>')
    for value in ['onclick', 'javascript:', 'background-image', '<svg', '<iframe', '<form', '<button']:
        assert value not in result
    assert 'color:red' in result


def png():
    buffer = io.BytesIO()
    Image.new('RGBA', (480, 120), (30, 80, 140, 255)).save(buffer, format='PNG')
    return SimpleUploadedFile('logo.png', buffer.getvalue(), content_type='image/png')


def test_branding_upload_replace_delete_and_login(client, community, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    users, _, _, _ = community
    client.force_login(users['alice'])
    assert client.post(reverse('company_settings'), {'name': 'test', 'logo': png()}).status_code == 403
    client.force_login(users['admin'])
    assert client.post(reverse('company_settings'), {'name': 'Example company', 'logo': png()}).status_code == 302
    branding = CompanyBranding.objects.get(pk=1)
    old = branding.logo.name
    assert branding.logo.storage.exists(old)
    response = client.get(reverse('board_index'))
    assert 'company-brand-logo' in response.content.decode()
    client.logout()
    response = client.get(reverse('login'))
    assert 'login-company-brand' in response.content.decode()
    assert 'createsuperuser' not in response.content.decode()
    response = client.get(reverse('company_logo'))
    assert response.status_code == 200 and response['Content-Type'] == 'image/png'
    assert b''.join(response.streaming_content).startswith(b'\x89PNG')
    client.force_login(users['admin'])
    assert client.post(reverse('company_settings'), {'name': 'new', 'logo': png()}).status_code == 302
    assert not branding.logo.storage.exists(old)
    response = client.post(reverse('company_settings'), {'name': 'new', 'logo': SimpleUploadedFile('x.svg', b'<svg onload="alert(1)"></svg>')})
    assert response.status_code == 200 and response.context['form'].errors
    assert client.post(reverse('company_settings'), {'action': 'delete'}).status_code == 302
    branding.refresh_from_db()
    assert not branding.logo
    assert client.get(reverse('company_logo')).status_code == 404


def test_csrf_required(client, community):
    from django.test import Client
    users, board, _, posts = community
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(users['admin'])
    assert strict.post(url('board_delete', board)).status_code == 403
    assert strict.post(url('board_post', board, posts['alice']), {'body': 'hello'}).status_code == 403
