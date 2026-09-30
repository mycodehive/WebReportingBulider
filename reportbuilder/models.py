import json
import uuid

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


def upload_path(instance, filename):
    from pathlib import Path
    return f"private/{instance.owner_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class Owned(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Connection(Owned):
    kind = models.CharField(max_length=32)
    config = models.JSONField(default=dict)
    encrypted_secrets = models.TextField(blank=True)
    upload = models.FileField(upload_to=upload_path, blank=True)
    groups = models.ManyToManyField(Group, blank=True)
    allowed_objects = models.JSONField(default=list, blank=True)
    allowed_columns = models.JSONField(default=dict, blank=True)
    masks = models.JSONField(default=dict, blank=True)
    row_policy = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, default="UNTESTED")
    last_test_at = models.DateTimeField(null=True, blank=True)

    def set_secrets(self, secrets):
        self.encrypted_secrets = Fernet(settings.REPORT_SECRET_KEY.encode()).encrypt(
            json.dumps(secrets).encode()
        ).decode() if secrets else ""

    def runtime_config(self):
        value = dict(self.config)
        if self.encrypted_secrets:
            value.update(json.loads(Fernet(settings.REPORT_SECRET_KEY.encode()).decrypt(self.encrypted_secrets.encode())))
        if self.upload:
            value["path"] = self.upload.path
        if self.kind == "rest":
            value["allowed_hosts"] = settings.REPORT_REST_ALLOWED_HOSTS
        return value

    def __str__(self):
        return self.name


class Project(Owned):
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Report(Owned):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="reports")
    definition = models.JSONField(default=dict)
    bindings = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    viewer_groups = models.ManyToManyField(Group, blank=True)

    def __str__(self):
        return self.name


class Revision(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    definition = models.JSONField()
    bindings = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["report", "number"], name="report_revision_unique")]


class Publication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name="publication")
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class Asset(Owned):
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE)
    file = models.FileField(upload_to=upload_path)
    mime = models.CharField(max_length=64, default="image/png")


class Execution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default="RUNNING")
    page_count = models.PositiveIntegerField(default=0)
    row_count = models.PositiveIntegerField(default=0)
    parameters = models.JSONField(default=dict)  # parameter names only; values are intentionally not logged
    created_at = models.DateTimeField(auto_now_add=True)
    error_code = models.CharField(max_length=60, blank=True)
    definition_snapshot = models.JSONField(default=dict)
    datasets_snapshot = models.JSONField(default=dict)
    bindings_snapshot = models.JSONField(default=list)
    rendered_html = models.TextField(blank=True)
    policy_fingerprint = models.CharField(max_length=64, blank=True)


class AuditEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    resource_id = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict)


class ApiToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    digest = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    report_ids = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    enabled = models.BooleanField(default=True)


class EmbedNonce(models.Model):
    nonce = models.CharField(max_length=64, primary_key=True)
    expires_at = models.DateTimeField()
