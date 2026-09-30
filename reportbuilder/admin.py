from django.contrib import admin
from .models import ApiToken, Asset, AuditEvent, Connection, Execution, Project, Publication, Report, Revision


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "owner", "status"]
    exclude = ["encrypted_secrets", "config"]
    filter_horizontal = ["groups"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "revision", "enabled"]
    filter_horizontal = ["viewer_groups"]
    readonly_fields = ["definition", "bindings", "revision"]


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    readonly_fields = ["report", "number", "definition", "bindings", "created_at"]
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([Project, Asset, Publication, Execution, AuditEvent])
@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "enabled", "expires_at"]
    readonly_fields = ["digest"]
    def has_add_permission(self, request):
        return False
admin.site.site_header = "WebReportingBuilder 관리"
