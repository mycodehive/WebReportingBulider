"""Infer a canonical origin only from a single explicitly trusted deployment host."""
import ipaddress

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def inferred_service_url():
    hosts = set()
    for raw_host in settings.ALLOWED_HOSTS:
        host = raw_host.strip().lower().rstrip('.')
        if not host or '*' in host or host.startswith('.') or '.' not in host or host.endswith('.localhost'):
            continue
        try:
            ipaddress.ip_address(host.strip('[]'))
            continue
        except ValueError:
            pass
        origin = f'https://{host}'
        try:
            URLValidator(schemes=['https'])(origin)
        except ValidationError:
            continue
        hosts.add(origin)
    return next(iter(hosts)) if len(hosts) == 1 else ''
