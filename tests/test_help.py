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
