import io

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.core.management import call_command
from django.db import transaction

from .models import (
    ApiToken, Asset, AuditEvent, Board, BoardCategory, BoardPost, BoardReply, BoardStatus,
    CompanyBranding, Connection, Execution, ManualVersion, Project,
    Publication, Report, Revision, WorkspaceMenu,
)


MENU_GUIDES = {
    "User": ("관리자에서 계정을 만들고 상태·권한을 관리합니다.", "새 계정 등록 시 데모 보고서를 준비하며, 사용자 목록의 작업 메뉴에서 선택 사용자의 데모를 다시 생성할 수 있습니다."),
    "Connection": ("데이터 연결과 자격 증명을 관리합니다.", "보고서 데이터셋이 이 연결을 참조합니다. 일반 사용자는 자신이 소유한 연결만 선택할 수 있습니다."),
    "Report": ("보고서 정의와 소유자, 공유 권한을 관리합니다.", "보고서는 프로젝트에 속하고 연결을 데이터셋에 매핑합니다. 게시와 버전 이력은 별도 메뉴에서 관리합니다."),
    "Project": ("보고서를 묶는 작업 공간입니다.", "프로젝트에 여러 보고서와 이미지 자산이 연결됩니다."),
    "Revision": ("저장된 보고서 버전 스냅샷을 조회합니다.", "보고서가 저장되거나 게시될 때 생성되며 Publication이 특정 버전을 참조합니다."),
    "Publication": ("외부 공개 링크와 게시 상태를 관리합니다.", "각 게시본은 보고서와 게시된 Revision을 연결합니다. 보고서 링크를 중지하면 공개 열람이 차단됩니다."),
    "Execution": ("보고서 실행 이력과 결과 상태를 확인합니다.", "실행은 Report와 Revision에 종속됩니다. 문제 해결 및 운영 감사에 사용됩니다."),
    "Asset": ("보고서 대표 이미지와 프로젝트 파일을 관리합니다.", "Report의 대표 이미지와 Project의 파일이 이 자산을 참조합니다."),
    "ApiToken": ("외부 API 접근 토큰의 범위와 만료를 관리합니다.", "토큰은 사용자 및 허용 보고서·기능 범위에 종속됩니다. 토큰 원문은 저장하거나 표시하지 않습니다."),
    "AuditEvent": ("주요 변경과 접근 감사 기록을 확인합니다.", "보고서·연결·공유 작업 등 다른 메뉴에서 수행된 작업의 추적 기록입니다."),
    "Board": ("게시판 이름, 유형, 관리자·운영자와 게시 허용 설정을 관리합니다.", "게시판은 카테고리·상태·게시글·답변의 상위 항목입니다."),
    "BoardCategory": ("게시판의 게시글 분류를 관리합니다.", "각 항목은 Board 하나에 소속되고 게시글이 선택적으로 참조합니다."),
    "BoardStatus": ("질문답변 게시판의 처리 상태를 관리합니다.", "각 상태는 Board 하나에 소속되고 게시글의 진행 상황을 표시합니다."),
    "BoardPost": ("게시판 게시글을 조회하고 관리합니다.", "글은 Board와 작성자에 연결되며 답변과 카테고리·상태가 연관됩니다."),
    "BoardReply": ("게시글의 답변·댓글을 관리합니다.", "각 답변은 하나의 BoardPost에 속합니다."),
    "CompanyBranding": ("로그인 화면과 워크스페이스의 회사 이름·로고를 설정합니다.", "등록한 로고가 공통 헤더 및 로그인 화면에 표시됩니다."),
    "WorkspaceMenu": ("좌측 워크스페이스 메뉴를 생성·수정·삭제하고 노출을 관리합니다.", "URL은 사이트 내부 경로만 허용합니다. 순서와 관리자 전용 여부가 사용자별 메뉴 표시를 결정합니다."),
    "ManualVersion": ("관리자용·사용자용 매뉴얼을 버전별로 편집하고 공개 버전을 선택합니다.", "각 대상은 한 공개 버전을 사용하며 /manual/ 화면에 해당 버전이 표시됩니다."),
}


class ExplainedModelAdmin(admin.ModelAdmin):
    change_list_template = "admin/reportbuilder/change_list.html"
    list_per_page = 50

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["menu_guide"] = MENU_GUIDES.get(self.model.__name__)
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(Connection)
class ConnectionAdmin(ExplainedModelAdmin):
    list_display = ["name", "kind", "owner", "status"]
    list_filter = ["kind", "status"]
    search_fields = ["name", "owner__username", "owner__email"]
    exclude = ["encrypted_secrets", "config"]
    filter_horizontal = ["groups"]


@admin.register(Report)
class ReportAdmin(ExplainedModelAdmin):
    list_display = ["name", "owner", "project", "revision", "enabled", "updated_at"]
    list_filter = ["enabled"]
    search_fields = ["name", "owner__username", "owner__email"]
    filter_horizontal = ["viewer_groups"]
    readonly_fields = ["definition", "bindings", "revision"]


@admin.register(Revision)
class RevisionAdmin(ExplainedModelAdmin):
    list_display = ["report", "number", "created_at"]
    search_fields = ["report__name", "report__owner__username"]
    readonly_fields = ["report", "number", "definition", "bindings", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Project)
class ProjectAdmin(ExplainedModelAdmin):
    list_display = ["name", "owner", "updated_at"]
    search_fields = ["name", "owner__username", "owner__email"]


@admin.register(Asset)
class AssetAdmin(ExplainedModelAdmin):
    list_display = ["name", "owner", "project", "mime", "created_at"]
    search_fields = ["name", "owner__username"]
    readonly_fields = ["file", "mime"]


@admin.register(Publication)
class PublicationAdmin(ExplainedModelAdmin):
    list_display = ["report", "revision", "enabled", "updated_at"]
    list_filter = ["enabled"]
    search_fields = ["report__name", "report__owner__username"]


@admin.register(Execution)
class ExecutionAdmin(ExplainedModelAdmin):
    list_display = ["report", "user", "status", "row_count", "page_count", "created_at"]
    list_filter = ["status"]
    search_fields = ["report__name", "user__username", "user__email"]
    readonly_fields = [field.name for field in Execution._meta.fields]


@admin.register(AuditEvent)
class AuditEventAdmin(ExplainedModelAdmin):
    list_display = ["action", "resource_id", "user", "created_at"]
    list_filter = ["action"]
    search_fields = ["action", "resource_id", "user__username", "user__email"]
    readonly_fields = [field.name for field in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(ApiToken)
class ApiTokenAdmin(ExplainedModelAdmin):
    list_display = ["name", "user", "enabled", "expires_at"]
    list_filter = ["enabled"]
    search_fields = ["name", "user__username", "user__email"]
    readonly_fields = ["digest"]

    def has_add_permission(self, request):
        return False


@admin.register(Board)
class BoardAdmin(ExplainedModelAdmin):
    list_display = ["name", "slug", "kind", "active", "allow_user_posts", "allow_replies"]
    list_filter = ["kind", "active"]
    search_fields = ["name", "slug"]
    filter_horizontal = ["managers", "operators"]


@admin.register(BoardCategory)
class BoardCategoryAdmin(ExplainedModelAdmin):
    list_display = ["name", "board", "order"]
    search_fields = ["name", "board__name"]


@admin.register(BoardStatus)
class BoardStatusAdmin(ExplainedModelAdmin):
    list_display = ["name", "board", "color", "order"]
    search_fields = ["name", "board__name"]


@admin.register(BoardPost)
class BoardPostAdmin(ExplainedModelAdmin):
    list_display = ["title", "board", "author", "status", "pinned", "created_at"]
    list_filter = ["board", "pinned"]
    search_fields = ["title", "author__username", "author__email"]


@admin.register(BoardReply)
class BoardReplyAdmin(ExplainedModelAdmin):
    list_display = ["post", "author", "created_at"]
    search_fields = ["post__title", "author__username", "author__email"]


@admin.register(CompanyBranding)
class CompanyBrandingAdmin(ExplainedModelAdmin):
    list_display = ["name", "updated_at"]


@admin.register(WorkspaceMenu)
class WorkspaceMenuAdmin(ExplainedModelAdmin):
    list_display = ["label", "url", "order", "staff_only", "active"]
    list_editable = ["order", "staff_only", "active"]
    list_filter = ["staff_only", "active"]
    search_fields = ["key", "label", "url"]


@admin.register(ManualVersion)
class ManualVersionAdmin(ExplainedModelAdmin):
    list_display = ["audience", "version", "is_published", "updated_at", "created_by"]
    list_filter = ["audience", "is_published"]
    search_fields = ["version", "content"]
    fields = ["audience", "version", "content", "is_published", "created_by"]
    readonly_fields = ["created_by"]

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            if obj.is_published:
                ManualVersion.objects.filter(audience=obj.audience).exclude(pk=obj.pk).update(is_published=False)
            if not obj.created_by_id:
                obj.created_by = request.user
            super().save_model(request, obj, form, change)


User = get_user_model()


@admin.action(description="선택한 사용자 데모 보고서 생성 / 초기화")
def generate_demo_reports(modeladmin, request, queryset):
    users = queryset.filter(is_active=True)
    count = 0
    for user in users.iterator():
        call_command("seed_demo", user_id=str(user.pk), reset=True, stdout=io.StringIO())
        count += 1
    messages.success(request, f"선택한 활성 사용자 {count}명의 데모 보고서를 초기화하고 다시 생성했습니다.")


class WorkspaceUserAdmin(ExplainedModelAdmin, UserAdmin):
    actions = [generate_demo_reports]
    change_list_template = "admin/reportbuilder/change_list.html"

    def save_model(self, request, obj, form, change):
        is_new = obj._state.adding
        super().save_model(request, obj, form, change)
        if is_new and obj.is_active:
            call_command("seed_demo", user_id=str(obj.pk), stdout=io.StringIO())


admin.site.unregister(User)
admin.site.register(User, WorkspaceUserAdmin)
admin.site.site_header = "WebReporting Builder 관리자"
admin.site.site_title = "WebReporting Builder"
admin.site.index_title = "관리 메뉴"
