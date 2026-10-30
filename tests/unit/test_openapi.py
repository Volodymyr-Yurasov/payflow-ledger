"""The OpenAPI spec is valid and describes exactly the routes the app serves."""

import re

import yaml
from openapi_spec_validator import validate

from app import create_app
from app.config import Config
from tests.helpers import load_spec

DOC_ENDPOINTS = {"static", "docs.openapi_spec", "docs.swagger_ui"}


def make_app():
    # No request here touches the database, so a dummy URL is enough.
    return create_app(
        Config(database_url="postgresql+psycopg://user@localhost/unused_test", webhook_secret="s")
    )


def test_spec_is_valid_openapi():
    validate(load_spec())


def test_spec_documents_exactly_the_api_routes():
    app = make_app()
    served = {
        (re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule), method.lower())
        for rule in app.url_map.iter_rules()
        if rule.endpoint not in DOC_ENDPOINTS
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    documented = {
        (path, method) for path, operations in load_spec()["paths"].items() for method in operations
    }
    assert served == documented


def test_spec_and_swagger_ui_are_served():
    client = make_app().test_client()

    spec = client.get("/openapi.yaml")
    assert spec.status_code == 200
    assert spec.mimetype == "application/yaml"
    assert yaml.safe_load(spec.data) == load_spec()

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert b'url: "/openapi.yaml"' in docs.data
