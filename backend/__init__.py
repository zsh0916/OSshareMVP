"""Smart Office backend package.

The public entry points are :mod:`backend.web_api` for HTTP traffic and
:mod:`backend.feishu_worker` for the Feishu event worker. Business modules
remain independently testable and can be replaced without changing clients.
"""
