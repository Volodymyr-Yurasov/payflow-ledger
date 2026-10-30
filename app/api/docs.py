"""API documentation: the hand-written OpenAPI spec and a Swagger UI page for it."""

from pathlib import Path

from flask import Blueprint, send_file

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi.yaml"

# Swagger UI is loaded by the browser from a CDN; nothing extra to install or serve.
_SWAGGER_UI = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>PayFlow Ledger API</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
  <script>SwaggerUIBundle({url: "/openapi.yaml", dom_id: "#swagger-ui"});</script>
</body>
</html>
"""

bp = Blueprint("docs", __name__)


@bp.get("/openapi.yaml")
def openapi_spec():
    return send_file(SPEC_PATH, mimetype="application/yaml")


@bp.get("/docs")
def swagger_ui():
    return _SWAGGER_UI
