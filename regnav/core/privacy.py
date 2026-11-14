"""Fail closed before creating an LLM client in local mode."""
import ipaddress
import os
from urllib.parse import urlsplit


def local_only():
    value = os.environ.get('REGNAV_LOCAL_ONLY', '1')
    if value not in {'0', '1'}:
        raise ValueError('REGNAV_LOCAL_ONLY must be 0 or 1')
    return value == '1'


def check_provider(kind, base_url=None):
    if kind not in {'extractive', 'openai', 'gigachat'}:
        raise ValueError('Unknown REGNAV_LLM')
    if not local_only() or kind == 'extractive':
        return
    if kind != 'openai':
        raise ValueError('External provider disabled in local mode')
    url = urlsplit(base_url or '')
    allowed = {x.strip() for x in os.environ.get('REGNAV_LOCAL_MODEL_HOSTS', '').split(',') if x.strip()}
    try:
        loopback = ipaddress.ip_address(url.hostname or '').is_loopback
    except ValueError:
        loopback = False
    if (url.scheme not in {'http', 'https'} or url.username or url.password
            or url.query or url.fragment or not (loopback or url.hostname in allowed)):
        raise ValueError('Local model must use a loopback IP or explicitly allowed host')
