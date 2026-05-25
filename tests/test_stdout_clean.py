"""On a search, stdout must be pure JSON; nothing else may leak."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_stdout_is_clean_json(tmp_path, bundled_settings):
    log = tmp_path / "out.log"
    code = (
        "import json, sys\n"
        "from typer.testing import CliRunner\n"
        "from sift.cli import app\n"
        f"r = CliRunner().invoke(app, ['search','hello','--engines','wikipedia',"
        f"'--settings',{str(bundled_settings)!r},'--log-file',{str(log)!r}], mix_stderr=False)\n"
        "sys.stdout.write(r.stdout)\n"
    )
    # We're stubbing the engine via a subprocess wouldn't be easy; instead just
    # invoke directly and assert stdout from CliRunner is parseable JSON.
    from typer.testing import CliRunner
    from sift.cli import app

    # Patch processors so we don't hit the network.
    import sift.bootstrap as bs
    bs.bootstrap(log_file=log)
    import sift.runner as runner
    runner._initialize_once()
    import searx.search as ss

    class StubProcessor:
        class engine:
            timeout = 1.0
        def get_params(self, sq, category): return {}
        def extend_container_if_suspended(self, c): return False
        def search(self, q, p, c, st, t):
            c.extend("wikipedia", [{"url": "https://example.org/u", "title": "t", "content": "", "engine": "wikipedia"}])

    ss.PROCESSORS["wikipedia"] = StubProcessor()
    from searx.search.models import EngineRef
    import sift.engines as eng
    orig = eng.resolve_engines
    eng.resolve_engines = lambda names, category: [EngineRef("wikipedia", "general")]
    try:
        r = CliRunner().invoke(app, [
            "search", "hello", "--engines", "wikipedia",
            "--log-file", str(log),
        ])
    finally:
        eng.resolve_engines = orig

    assert r.exit_code == 0, r.stdout
    # Every non-empty stdout line should be part of one JSON document.
    data = json.loads(r.stdout)
    assert data["results"][0]["url"] == "https://example.org/u"
    # No log markers leaked.
    for line in r.stdout.splitlines():
        assert " WARNING " not in line
        assert " ERROR " not in line


def test_synthesize_stdout_is_clean_json():
    import json
    from unittest.mock import patch
    from typer.testing import CliRunner
    from sift.cli import app

    payload = json.dumps({"query": "q", "results": [{"url": "u", "markdown": "x"}]})
    env = {"SIFT_LLM_HOST": "http://x", "SIFT_LLM_MODEL": "m", "SIFT_LLM_APIKEY": "-"}

    async def fake(query, results, cfg, **kw):
        return "ans", None

    with patch("sift.llm.synthesize_search_results", side_effect=fake):
        r = CliRunner().invoke(app, ["synthesize", "q"], input=payload, env=env)
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["summary"] == "ans"


def test_describe_stdout_is_clean_json(tmp_path):
    import json
    from unittest.mock import patch
    from typer.testing import CliRunner
    from sift.cli import app
    from test_images import TINY_PNG

    p = tmp_path / "x.png"
    p.write_bytes(TINY_PNG)
    env = {
        "SIFT_LLM_HOST": "http://x", "SIFT_LLM_MODEL": "m",
        "SIFT_LLM_APIKEY": "-", "SIFT_VLM": "1",
    }

    async def fake(image_data, mime, cfg, prompt=None):
        return "a tiny square", None

    with patch("sift.llm.process_image_content", side_effect=fake):
        r = CliRunner().invoke(app, ["describe", str(p)], env=env)
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["success"] is True
