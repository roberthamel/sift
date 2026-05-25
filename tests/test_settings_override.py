"""Bootstrap honors --settings PATH (verified in a subprocess for isolation).

Bootstrapping permanently configures searx in the importing process, so we
cannot mutate settings across tests in the same interpreter without leaking
state into other tests.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


SETTINGS_YAML = textwrap.dedent(
    """
    general: {debug: false, instance_name: x-override, enable_metrics: false}
    brand: {}
    search:
      safe_search: 0
      autocomplete: ''
      favicon_resolver: ''
      default_lang: auto
      ban_time_on_fail: 5
      max_ban_time_on_fail: 60
      formats: [json]
    server: {secret_key: deadbeef}
    redis: {url: false}
    ui: {}
    outgoing: {request_timeout: 3.0}
    categories_as_tabs: {general: {}}
    engines: []
    """
).strip()


def test_explicit_settings_path(tmp_path):
    cfg = tmp_path / "tiny.yml"
    cfg.write_text(SETTINGS_YAML)
    log = tmp_path / "x.log"

    code = (
        f"from pathlib import Path\n"
        f"from sift.bootstrap import bootstrap\n"
        f"bootstrap(settings_path=Path({str(cfg)!r}), log_file=Path({str(log)!r}))\n"
        f"import searx\n"
        f"print(searx.settings['general']['instance_name'])\n"
        f"print(len(searx.settings['engines']))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[0] == "x-override"
    assert lines[1] == "0"
    assert log.exists()
