from typer.testing import CliRunner

from sift.cli import app


def test_root_help():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "Usage:" in r.stdout
    assert "search" in r.stdout


def test_search_help():
    r = CliRunner().invoke(app, ["search", "--help"])
    assert r.exit_code == 0
    assert "--engines" in r.stdout
    assert "--pretty" in r.stdout
    assert "--summary" in r.stdout
    assert "--allow" in r.stdout
    assert "--block" in r.stdout
    assert "--cache-ttl" in r.stdout


def test_synthesize_help():
    r = CliRunner().invoke(app, ["synthesize", "--help"])
    assert r.exit_code == 0
    assert "--llm-host" in r.stdout
    assert "--llm-model" in r.stdout


def test_describe_help():
    r = CliRunner().invoke(app, ["describe", "--help"])
    assert r.exit_code == 0
    assert "--vlm" in r.stdout
    assert "--max-bytes" in r.stdout


def test_fetch_help():
    r = CliRunner().invoke(app, ["fetch", "--help"])
    assert r.exit_code == 0
    assert "--prompt" in r.stdout


def test_cache_help():
    r = CliRunner().invoke(app, ["cache", "--help"])
    assert r.exit_code == 0
    assert "stats" in r.stdout
    assert "clear" in r.stdout
