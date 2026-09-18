"""Lazily-created boto3 clients.

Lazy on purpose: importing this module must never create a client, so the
whole app still imports and every offline test still runs on a machine with
no AWS credentials at all.

Credentials come from the environment's own chain -- SSO locally, an IAM role
on Lambda. Nothing here reads an access key, and nothing here should ever
start doing so.
"""

from __future__ import annotations

from functools import lru_cache

from . import config


def _client(service: str):
    import boto3  # imported here so `import app` never needs boto3 present

    return boto3.client(service, region_name=config.AWS_REGION)


@lru_cache(maxsize=1)
def textract():
    return _client("textract")


@lru_cache(maxsize=1)
def bedrock_runtime():
    return _client("bedrock-runtime")


@lru_cache(maxsize=1)
def s3():
    return _client("s3")


@lru_cache(maxsize=1)
def dynamodb():
    return _client("dynamodb")


def reset() -> None:
    """Drop cached clients. Tests use this; Lambda never needs it."""
    for fn in (textract, bedrock_runtime, s3, dynamodb):
        fn.cache_clear()
