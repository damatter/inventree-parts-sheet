"""Website publishing compatible with the former Part Visibility screen."""

import json
import logging
import os
import uuid

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone

from . import __version__
from .services import require_part


def configured():
    return bool(os.environ.get("WEBSITE_SYNC_LAMBDA_ARN", "").strip())


def request_sync(user):
    require_part(user, "change")
    function = os.environ.get("WEBSITE_SYNC_LAMBDA_ARN", "").strip()
    if not function:
        return JsonResponse({"error": "Website sync is not configured on this server."}, status=503)
    key = "part-visibility:website-sync-cooldown"  # Shared during migration from the old plugin.
    request_id = uuid.uuid4().hex
    if not cache.add(key, request_id, timeout=60):
        return JsonResponse({"message": "Website sync was already queued recently."}, status=202)
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "lambda",
            region_name=os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "ca-central-1",
            config=Config(
                connect_timeout=3, read_timeout=10, retries={"max_attempts": 2, "mode": "standard"}
            ),
        )
        result = client.invoke(
            FunctionName=function,
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "source": "inventree-part-visibility",
                    "action": "sync-website",
                    "requestId": request_id,
                    "requestedAt": timezone.now().isoformat(),
                    "pluginVersion": __version__,
                }
            ).encode("utf-8"),
        )
        if result.get("StatusCode") != 202:
            raise RuntimeError("Lambda did not accept the sync request")
    except Exception:
        cache.delete(key)
        logging.getLogger(__name__).exception("Could not queue website sync")
        return JsonResponse(
            {"error": "Website sync could not be queued. Check the server logs."}, status=502
        )
    return JsonResponse({"message": "Website sync queued.", "request_id": request_id}, status=202)
