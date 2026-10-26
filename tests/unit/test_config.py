import pytest

from mindmesh.config import DEFAULT_DEV_KEY, ConfigError, Settings
from mindmesh.server.app import create_app
from mindmesh.server.tokens import issue_stream_token, verify_stream_token

STRONG = "k" * 40
PROD = {
    "MINDMESH_ENV": "production",
    "MINDMESH_API_KEY": STRONG,
    "MINDMESH_SECRET_KEY": "s" * 40,
    "MINDMESH_DATABASE_URL": "postgresql://u:p@db:5432/mindmesh",
    "MINDMESH_CORS_ORIGINS": "https://studio.example.com",
}


def test_valid_production_settings():
    s = Settings.from_env(PROD)
    assert s.validate() == []
    assert s.docs is False and s.cors_origins == ["https://studio.example.com"]


@pytest.mark.parametrize("override, message", [
    ({"MINDMESH_API_KEY": ""}, "MINDMESH_API_KEY is not set"),
    ({"MINDMESH_API_KEY": DEFAULT_DEV_KEY}, "public development key"),
    ({"MINDMESH_API_KEY": "short"}, "at least 32"),
    ({"MINDMESH_SECRET_KEY": ""}, "MINDMESH_SECRET_KEY is not set"),
    ({"MINDMESH_CORS_ORIGINS": "*"}, "not '*'"),
    ({"MINDMESH_DATABASE_URL": "sqlite:///x.db"}, "PostgreSQL"),
    ({"MINDMESH_DATABASE_URL": ""}, "PostgreSQL"),
])
def test_unsafe_production_settings_are_rejected(override, message):
    with pytest.raises(ConfigError, match=message):
        Settings.from_env({**PROD, **override}).validate()


def test_production_refuses_to_build_app():
    with pytest.raises(ConfigError):
        create_app(settings=Settings.from_env({"MINDMESH_ENV": "production"}))


def test_development_defaults_only_warn():
    s = Settings.from_env({})
    assert s.validate()  # warnings, no exception
    assert s.resolved_api_key() == DEFAULT_DEV_KEY and s.docs is True


@pytest.mark.parametrize("env", [{"MINDMESH_ENV": "staging"}, {"MINDMESH_CORS_ORIGINS": "localhost:5173"},
                                 {"MINDMESH_MAX_BODY_BYTES": "10"}])
def test_invalid_settings_rejected_in_any_environment(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env).validate()


def test_stream_tokens_are_bound_signed_and_expiring():
    t = issue_stream_token("secret", "prj_a", "run_1", 60, now=1000)
    assert verify_stream_token("secret", t, "run_1", now=1030) == "prj_a"
    assert verify_stream_token("secret", t, "run_2", now=1030) is None       # other run
    assert verify_stream_token("other", t, "run_1", now=1030) is None        # wrong secret
    assert verify_stream_token("secret", t, "run_1", now=1061) is None       # expired
    body, sig = t.split(".")
    forged = issue_stream_token("attacker", "prj_b", "run_1", 60, now=1000).split(".")[0] + "." + sig
    assert verify_stream_token("secret", forged, "run_1", now=1030) is None
    for junk in ("", "abc", "a.b", "....", "eyJ9.x"):
        assert verify_stream_token("secret", junk, "run_1") is None
