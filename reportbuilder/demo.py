"""Create account demos without rolling back the account when seeding fails."""
import io
import logging

from django.core.management import call_command
from django.db import transaction

logger = logging.getLogger(__name__)


def prepare_user_demo(user, *, reset=False):
    if not user.is_active:
        return False
    try:
        # A savepoint also protects callers inside Django admin's save transaction.
        with transaction.atomic():
            call_command("seed_demo", user_id=str(user.pk), reset=reset, stdout=io.StringIO())
        return True
    except Exception:
        logger.exception("Demo report creation failed for user_id=%s", user.pk)
        return False
