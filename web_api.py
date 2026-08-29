"""Backward-compatible ASGI entry point.

Deployments may continue to run ``uvicorn web_api:app``. New integrations
should import ``backend.web_api:app`` directly.
"""

from backend.web_api import app

__all__ = ["app"]

