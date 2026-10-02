import csv
import io

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reportbuilder.definition import validate_definition
from reportbuilder.models import Connection, DemoSeed, Project, Publication, Report, Revision


def demo_definition():
    fields = [{"field_id": field_id, "object_id": "sales_rows", "alias": field_id, "label": label,
               "type": typ, "required": True, "nullable": False}
              for field_id, label, typ in [("department", "부서", "string"), ("customer", "고객명", "string"),
                                           ("amount", "금액", "decimal")]]
    def element(id, type, x, y, width, height, **properties):
        return {"element_id": id, "type": type,
                "geometry": {"x_mm": x, "y_mm": y, "width_mm": width, "height_mm": height},
                "style": {"font_size_pt": 10}, "overflow": "fixed_clip", **properties}
    def field(id, field_id, x, width, scope="row", **binding):
        return element(id, "field", x, 1, width, 6,
                       binding={"dataset_id": "sales", "field_id": field_id, "scope": scope, **binding})
    definition = {"schema_version": "1.0.0", "name": "매출 현황 예제", "parameters": [],
                  "datasets": [{"dataset_id": "sales", "alias": "sales", "cardinality": "many",
                                "objects": [{"object_id": "sales_rows", "alias": "sales_rows"}], "fields": fields,
                                "query": {"projection": [f["field_id"] for f in fields],
                                          "filters": {"op": "and", "items": []},
                                          "sorts": [{"field_id": "department", "direction": "asc", "nulls": "last"}],
                                          "groups": [], "aggregates": []}}],
                  "pages": [{"page_id": "sales_page", "kind": "flow", "width_mm": 210, "height_mm": 297,
                             "margins": {"top": 15, "right": 15, "bottom": 15, "left": 15},
                             "dataset_id": "sales", "elements": [], "bands": [
                                 {"band_id": "title_band", "type": "ReportHeader", "height_mm": 25,
                                  "elements": [element("title", "text", 0, 0, 180, 12, text="매출 현황 보고서"),
                                               element("subtitle", "text", 0, 14, 180, 7, text="합성 예제 데이터 · 부서별 고객 매출")]},
                                 {"band_id": "header", "type": "PageHeader", "height_mm": 10,
                                  "elements": [element("dept_label", "text", 0, 1, 50, 7, text="부서"),
                                               element("name_label", "text", 55, 1, 65, 7, text="고객명"),
                                               element("amount_label", "text", 130, 1, 50, 7, text="금액")]},
                                 {"band_id": "detail", "type": "Detail", "height_mm": 8,
                                  "elements": [field("dept", "department", 0, 50), field("customer", "customer", 55, 65),
                                               field("amount", "amount", 130, 50)]},
                                 {"band_id": "summary", "type": "ReportFooter", "height_mm": 12,
                                  "elements": [element("total_label", "text", 0, 1, 100, 6, text="매출 총액"),
                                               field("total", "amount", 130, 50, "aggregate", aggregate="sum")]},
                                 {"band_id": "footer", "type": "PageFooter", "height_mm": 8,
                                  "elements": [element("page_number", "page_number", 155, 1, 10, 6),
                                               element("page_slash", "text", 165, 1, 5, 6, text="/"),
                                               element("total_pages", "total_pages", 170, 1, 10, 6)]},
                             ]}]}
    validate_definition(definition)
    return definition


class Command(BaseCommand):
    help = "관리자에게 합성 예제를 추가합니다. --reset은 해당 예제 보고서만 초기화합니다."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--reset", action="store_true", help="기존 매출 예제만 정리하고 다시 생성")

    @transaction.atomic
    def handle(self, *args, **options):
        users = get_user_model().objects.filter(is_staff=True, is_active=True)
        if options["username"]:
            users = users.filter(username=options["username"])
        user = users.first()
        if not user:
            raise CommandError("먼저 createsuperuser로 관리자 계정을 생성하세요.")
        marker, _ = DemoSeed.objects.get_or_create(owner=user)
        marker = DemoSeed.objects.select_for_update().get(pk=marker.pk)
        existing = Report.objects.filter(owner=user, name="매출 현황 예제")
        if options["reset"]:
            removed_reports, removed_connections = reset_demo(user)
            self.stdout.write(f"기존 예제 초기화: 보고서 {removed_reports}개, 미사용 예제 연결 {removed_connections}개 정리")
        elif existing.exists():
            marker.completed = True
            marker.save(update_fields=["completed"])
            self.stdout.write("예제가 이미 존재합니다. 다시 만들려면 --reset 옵션을 사용하세요.")
            return
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(["department", "customer", "amount"])
        for index in range(65):
            writer.writerow([f"영업 {index // 25 + 1}팀", f"예제 고객 {index + 1:02d}", 100000 + index * 2500])
        connection = Connection.objects.create(owner=user, name="합성 매출 CSV", kind="csv", config={"encoding": "utf-8-sig"},
                                                upload=ContentFile(text.getvalue().encode("utf-8-sig"), name="sales.csv"))
        project = Project.objects.create(owner=user, name="매출 현황 예제")
        binding = {"dataset_id": "sales", "connection_id": str(connection.pk),
                   "object_mappings": {"sales_rows": {"schema": None, "object": "sales"}},
                   "field_mappings": {id: {"column": id, "conversion": "to_decimal" if id == "amount" else "identity"}
                                      for id in ["department", "customer", "amount"]}}
        # File object names are the server filename stem; use introspection instead of assuming the client filename.
        from reportbuilder.data import introspect
        binding["object_mappings"]["sales_rows"]["object"] = introspect("csv", connection.runtime_config())["objects"][0]["object"]
        definition = demo_definition()
        report = Report.objects.create(owner=user, project=project, name="매출 현황 예제", definition=definition,
                                       bindings=[binding], revision=1)
        Revision.objects.create(report=report, number=1, definition=definition, bindings=[binding])
        marker.completed = True
        marker.save(update_fields=["completed"])
        self.stdout.write(self.style.SUCCESS(f"예제 준비 완료: /reports/{report.pk}/design/"))


def binding_connection_ids(bindings):
    if not isinstance(bindings, list):
        return set()
    return {str(binding["connection_id"]) for binding in bindings
            if isinstance(binding, dict) and binding.get("connection_id")}


def reset_demo(user):
    """Delete only this user's named demo reports and unshared source files."""
    reports = list(Report.objects.select_for_update().filter(owner=user, name="매출 현황 예제"))
    report_ids = [report.pk for report in reports]
    connection_ids = set()
    for report in reports:
        connection_ids.update(binding_connection_ids(report.bindings))
        for revision in report.revisions.only("bindings"):
            connection_ids.update(binding_connection_ids(revision.bindings))

    # Publications protect revisions, so remove publication rows before deleting the demo reports.
    Publication.objects.filter(report__in=reports).delete()

    for report in reports:
        project_id = report.project_id
        report.delete()  # revisions and execution snapshots cascade with the report
        project = Project.objects.filter(pk=project_id, owner=user, name="매출 현황 예제").first()
        if project and not project.reports.exists() and not project.asset_set.exists():
            project.delete()

    referenced = set()
    for report in Report.objects.only("bindings").iterator():
        referenced.update(binding_connection_ids(report.bindings))
    for revision in Revision.objects.only("bindings").iterator():
        referenced.update(binding_connection_ids(revision.bindings))

    removed_connections = 0
    for connection in Connection.objects.filter(pk__in=connection_ids, owner=user,
                                                 name="합성 매출 CSV", kind="csv"):
        if str(connection.pk) not in referenced:
            if connection.upload:
                upload_name = connection.upload.name
                storage = connection.upload.storage
                transaction.on_commit(lambda storage=storage, upload_name=upload_name: storage.delete(upload_name))
            connection.delete()
            removed_connections += 1
    return len(report_ids), removed_connections
