from django.urls import path
from . import views
from . import analytics_views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("reports/", views.library, name="library"),
    path("reports/<uuid:report_id>/design/", views.designer, name="designer"),
    path("reports/<uuid:report_id>/", views.viewer, name="viewer"),
    path("reports/<uuid:report_id>/statistics/", analytics_views.statistics_view, name="statistics"),
    path("reports/<uuid:report_id>/statistics/export/<str:format>/", analytics_views.statistics_export, name="statistics_export"),
    path("reports/<uuid:report_id>/export/<str:format>/", views.report_export, name="report_export"),
    path("connections/", views.connections_page, name="connections"),
    path("manual/", views.manual, name="manual"),
    path("assets/<uuid:asset_id>/", views.asset_view, name="asset"),
    path("projects/import/", views.project_import, name="project_import"),
    path("published/<uuid:publication_id>/", views.publication_view, name="publication"),
    path("embed/", views.embed_view, name="embed"),
    path("api/reports/", views.reports_api),
    path("api/reports/<uuid:report_id>/", views.report_api),
    path("api/reports/<uuid:report_id>/bindings/", views.bindings_api),
    path("api/reports/<uuid:report_id>/preview/", views.preview_api),
    path("api/reports/<uuid:report_id>/publish/", views.publish_api),
    path("api/reports/<uuid:report_id>/execute/", views.execute_api),
    path("api/connections/", views.connections_api),
    path("api/connections/<uuid:connection_id>/test/", views.connection_test_api),
    path("api/connections/<uuid:connection_id>/schema/", views.schema_api),
    path("api/assets/", views.asset_api),
    path("api/embed-sessions/", views.embed_session),
]
