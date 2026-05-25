from typer.testing import CliRunner

from sift.cli import app


def test_unknown_engine_exits_1():
    r = CliRunner().invoke(app, ["search", "linux", "--engines", "definitely-not-an-engine"])
    assert r.exit_code == 1
