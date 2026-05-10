"""Web Push delivery using pywebpush.

Reads VAPID keys from env: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT.
Loads subscriptions from DB, sends payload to each, deletes 410-Gone subs.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PushPayload:
    title: str
    body: str
    url: str = "/proposals"


def send_to_all(payload: PushPayload) -> int:
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    subject = os.environ.get("VAPID_SUBJECT", "mailto:noreply@example.com").strip()

    if not private_key or not public_key:
        logger.warning("VAPID keys not configured; skipping web push")
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed; skipping web push")
        return 0

    from ai_agent.db.push_store import list_subscriptions, mark_used, remove_subscription

    subscriptions = list_subscriptions()
    if not subscriptions:
        logger.info("No push subscriptions registered")
        return 0

    sent = 0
    data = json.dumps({"title": payload.title, "body": payload.body, "url": payload.url})
    vapid_claims = {"sub": subject}

    for sub in subscriptions:
        sub_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=data,
                vapid_private_key=private_key,
                vapid_claims=vapid_claims,
                ttl=60 * 60 * 24,
            )
            mark_used(sub.endpoint)
            sent += 1
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status in (404, 410):
                logger.info("Subscription gone (HTTP %s); removing %s", status, sub.endpoint[:60])
                remove_subscription(sub.endpoint)
            else:
                logger.warning("Push failed for %s: %s (HTTP %s)", sub.endpoint[:60], exc, status)
        except Exception as exc:
            logger.exception("Unexpected push error for %s: %s", sub.endpoint[:60], exc)

    logger.info("Web push: sent %d / %d", sent, len(subscriptions))
    return sent
