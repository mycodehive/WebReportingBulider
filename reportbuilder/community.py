from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .community_forms import BoardForm, CategoryFormSet, PostForm, ReplyForm, StatusChangeForm, StatusFormSet, clean_html
from .models import Board, BoardPost, BoardReply, BoardStatus


def manager(board, user):
    return user.is_staff or board.managers.filter(pk=user.pk).exists()


def moderator(board, user):
    return manager(board, user) or board.operators.filter(pk=user.pk).exists()


def available_boards(user):
    if user.is_staff:
        return Board.objects.all()
    return Board.objects.filter(Q(active=True) | Q(managers=user) | Q(operators=user)).distinct()


def get_board(request, board_id):
    return get_object_or_404(available_boards(request.user), pk=board_id)


def visible_posts(board, user):
    posts = board.posts.select_related('author', 'category', 'status')
    return posts.filter(author=user) if board.kind == 'qa' and not moderator(board, user) else posts


def get_post(request, board, post_id):
    return get_object_or_404(visible_posts(board, request.user), pk=post_id)


def can_write(board, user):
    return moderator(board, user) or (board.active and board.allow_user_posts)


@login_required
@never_cache
@require_http_methods(['GET'])
def index(request):
    boards = list(available_boards(request.user))
    for board in boards:
        board.visible_count = visible_posts(board, request.user).count()
        board.can_manage = manager(board, request.user)
    return render(request, 'reportbuilder/boards/index.html', {'boards': boards})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def settings(request, board_id=None):
    board = get_board(request, board_id) if board_id else Board()
    if not (manager(board, request.user) if board_id else request.user.is_staff):
        return HttpResponseForbidden('게시판 설정은 관리자만 변경할 수 있습니다.')
    form = BoardForm(request.POST or None, instance=board)
    if request.method == 'POST' and form.is_valid():
        board = form.save()
        if not board.statuses.exists():
            for order, (name, color) in enumerate([('접수', '#2563eb'), ('보류', '#b45309'), ('완료', '#15803d')]):
                BoardStatus.objects.create(board=board, name=name, color=color, order=order)
        if board.kind == 'qa':
            board.posts.filter(status__isnull=True).update(status=board.statuses.first())
        messages.success(request, '게시판 설정을 저장했습니다. 카테고리와 상태도 설정할 수 있습니다.')
        return redirect('board_settings', board_id=board.pk)
    return render(request, 'reportbuilder/boards/settings.html', {'form': form, 'board': board if board_id else None})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def taxonomy(request, board_id):
    board = get_board(request, board_id)
    if not manager(board, request.user):
        return HttpResponseForbidden()
    categories = CategoryFormSet(request.POST or None, instance=board, prefix='categories')
    statuses = StatusFormSet(request.POST or None, instance=board, prefix='statuses')
    if request.method == 'POST':
        categories_valid = categories.is_valid()
        statuses_valid = statuses.is_valid()
        if categories_valid and statuses_valid:
            with transaction.atomic():
                categories.save()
                statuses.save()
                # A removed status falls back to the first remaining configured status.
                board.posts.filter(status__isnull=True).update(status=board.statuses.first() if board.kind == 'qa' else None)
            messages.success(request, '카테고리와 상태를 저장했습니다.')
            return redirect('board_taxonomy', board_id=board.pk)
    return render(request, 'reportbuilder/boards/taxonomy.html', {'board': board, 'categories': categories, 'statuses': statuses})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def board_delete(request, board_id):
    board = get_board(request, board_id)
    if not manager(board, request.user):
        return HttpResponseForbidden()
    if request.method == 'POST':
        board.delete()
        messages.success(request, '게시판과 게시글을 삭제했습니다.')
        return redirect('board_index')
    return render(request, 'reportbuilder/boards/delete.html', {'board': board, 'label': board.name, 'back_url': 'board_list'})


@login_required
@never_cache
@require_http_methods(['GET'])
def listing_by_slug(request, slug):
    board = get_object_or_404(available_boards(request.user), slug=slug)
    return listing(request, board.pk)


@login_required
@never_cache
@require_http_methods(['GET'])
def listing(request, board_id):
    board = get_board(request, board_id)
    posts = visible_posts(board, request.user)
    query = request.GET.get('q', '').strip()[:200]
    if query:
        posts = posts.filter(Q(title__icontains=query) | Q(body__icontains=query))
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    if category.isdecimal():
        posts = posts.filter(category_id=category)
    if status.isdecimal() and board.kind == 'qa':
        posts = posts.filter(status_id=status)
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'reportbuilder/boards/list.html', {
        'board': board, 'page': Paginator(posts, 20).get_page(request.GET.get('page')),
        'query': query, 'selected_category': category, 'selected_status': status, 'filter_query': params.urlencode(),
        'can_manage': manager(board, request.user), 'can_write': can_write(board, request.user),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def edit_post(request, board_id, post_id=None):
    board = get_board(request, board_id)
    post = get_post(request, board, post_id) if post_id else BoardPost(board=board, author=request.user)
    privileged = moderator(board, request.user)
    if (post_id and post.author_id != request.user.pk and not privileged) or (not post_id and not can_write(board, request.user)):
        return HttpResponseForbidden()
    form = PostForm(request.POST or None, instance=post, board=board, moderator=privileged)
    if request.method == 'POST' and form.is_valid():
        post = form.save(commit=False)
        if board.kind == 'qa' and not post.status_id:
            post.status = board.statuses.first()
        post.save()
        messages.success(request, '게시글을 저장했습니다.')
        return redirect('board_post', board_id=board.pk, post_id=post.pk)
    return render(request, 'reportbuilder/boards/form.html', {'board': board, 'form': form, 'post': post if post_id else None, 'heading': '게시글 수정' if post_id else '글쓰기'})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def detail(request, board_id, post_id):
    board = get_board(request, board_id)
    post = get_post(request, board, post_id)
    form = ReplyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        reply = form.save(commit=False)
        reply.post = post
        reply.author = request.user
        reply.save()
        post.save(update_fields=['updated_at'])
        messages.success(request, '답변 / 댓글을 등록했습니다.')
        return redirect('board_post', board_id=board.pk, post_id=post.pk)
    privileged = moderator(board, request.user)
    replies = list(post.replies.select_related('author'))
    for reply in replies:
        reply.safe_body = clean_html(reply.body)
        reply.can_edit = privileged or reply.author_id == request.user.pk
    response = render(request, 'reportbuilder/boards/detail.html', {
        'board': board, 'post': post, 'safe_body': clean_html(post.body), 'replies': replies, 'form': form,
        'can_edit': privileged or post.author_id == request.user.pk, 'moderator': privileged,
        'status_form': StatusChangeForm(board=board, initial={'status': post.status_id}),
    })
    response['Referrer-Policy'] = 'same-origin'
    return response


@login_required
@never_cache
@require_POST
def change_status(request, board_id, post_id):
    board = get_board(request, board_id)
    post = get_post(request, board, post_id)
    if board.kind != 'qa' or not moderator(board, request.user):
        return HttpResponseForbidden()
    form = StatusChangeForm(request.POST, board=board)
    if form.is_valid():
        post.status = form.cleaned_data['status']
        post.save(update_fields=['status', 'updated_at'])
        messages.success(request, '처리 상태를 변경했습니다.')
    else:
        messages.error(request, '이 게시판의 처리 상태를 선택해 주세요.')
    return redirect('board_post', board_id=board.pk, post_id=post.pk)


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def post_delete(request, board_id, post_id):
    board = get_board(request, board_id)
    post = get_post(request, board, post_id)
    if post.author_id != request.user.pk and not moderator(board, request.user):
        return HttpResponseForbidden()
    if request.method == 'POST':
        post.delete()
        return redirect('board_list', board_id=board.pk)
    return render(request, 'reportbuilder/boards/delete.html', {'board': board, 'post': post, 'label': post.title})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def reply_edit(request, board_id, post_id, reply_id):
    board = get_board(request, board_id)
    post = get_post(request, board, post_id)
    reply = get_object_or_404(BoardReply, pk=reply_id, post=post)
    if reply.author_id != request.user.pk and not moderator(board, request.user):
        return HttpResponseForbidden()
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        reply.delete()
        return redirect('board_post', board_id=board.pk, post_id=post.pk)
    form = ReplyForm(request.POST or None, instance=reply)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('board_post', board_id=board.pk, post_id=post.pk)
    return render(request, 'reportbuilder/boards/form.html', {'board': board, 'post': post, 'form': form, 'reply': reply, 'heading': '답변 / 댓글 수정'})


@login_required
@never_cache
@require_http_methods(['GET'])
def user_search(request):
    board_id = request.GET.get('board', '').strip()
    if board_id:
        board = get_object_or_404(Board, pk=board_id)
        if not manager(board, request.user):
            return HttpResponseForbidden()
    elif not request.user.is_staff:
        return HttpResponseForbidden()

    query = request.GET.get('q', '').strip()[:120]
    if len(query) < 2:
        return JsonResponse({'results': []})

    User = get_user_model()
    has_first_name = any(field.name == 'first_name' for field in User._meta.get_fields())
    has_last_name = any(field.name == 'last_name' for field in User._meta.get_fields())
    lookup = Q()
    for term in query.split():
        term_lookup = Q(username__icontains=term) | Q(email__icontains=term)
        if User.USERNAME_FIELD != 'username':
            term_lookup |= Q(**{f'{User.USERNAME_FIELD}__icontains': term})
        if has_first_name:
            term_lookup |= Q(first_name__icontains=term)
        if has_last_name:
            term_lookup |= Q(last_name__icontains=term)
        lookup &= term_lookup
    if query.isdecimal():
        lookup |= Q(pk=int(query))
    users = User.objects.filter(is_active=True).filter(lookup).order_by('username').distinct()[:20]
    results = []
    for user in users:
        full_name = user.get_full_name().strip() if hasattr(user, 'get_full_name') else ''
        results.append({
            'id': str(user.pk),
            'username': str(getattr(user, 'username', getattr(user, User.USERNAME_FIELD, ''))),
            'name': full_name or str(getattr(user, User.USERNAME_FIELD, user.pk)),
            'email': str(getattr(user, 'email', '') or ''),
        })
    response = JsonResponse({'results': results})
    response['Cache-Control'] = 'private, no-store'
    return response
