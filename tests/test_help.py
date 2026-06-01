from typer.testing import CliRunner

from sift.cli import app


def test_root_help():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "Usage:" in r.stdout
    assert "QUERY" in r.stdout
    assert "Commands:" not in r.stdout


def test_research_options_present():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "--mode" in r.stdout
    assert "--stream" in r.stdout
    assert "--allow" in r.stdout
    assert "--block" in r.stdout
    assert "--llm-host" in r.stdout
    assert "--embed-base-url" in r.stdout


def test_tui_flag_absent():
    r = CliRunner().invoke(app, ["--help"])
    assert "--tui" not in r.stdout


def test_output_flag_absent():
    r = CliRunner().invoke(app, ["--help"])
    assert "--output" not in r.stdout
    assert "-o" not in r.stdout


def test_continue_and_print_present():
    r = CliRunner().invoke(app, ["--help"])
    assert "--continue" in r.stdout
    assert "--print" in r.stdout
