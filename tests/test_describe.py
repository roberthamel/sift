from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from sift.cli import app
from test_images import TINY_PNG  # type: ignore


def _env(vlm: bool = True):
    return {
        "SIFT_LLM_HOST": "http://x",
        "SIFT_LLM_MODEL": "m",
        "SIFT_LLM_APIKEY": "-",
        **({"SIFT_VLM": "1"} if vlm else {"SIFT_VLM": ""}),
    }


def _fake_describe(description="a tiny red square", err=None):
    async def f(image_data, mime, cfg, prompt=None):
        return description, err
    return f


def test_describe_file(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(TINY_PNG)
    with patch("sift.llm.process_image_content", side_effect=_fake_describe()):
        r = CliRunner().invoke(app, ["describe", str(p)], env=_env())
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["success"] is True
    assert data["description"]
    assert data["mime"] == "image/png"


def test_describe_data_url():
    b64 = base64.b64encode(TINY_PNG).decode()
    src = f"data:image/png;base64,{b64}"
    with patch("sift.llm.process_image_content", side_effect=_fake_describe()):
        r = CliRunner().invoke(app, ["describe", src], env=_env())
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["success"] is True


def test_describe_raw_base64():
    b64 = base64.b64encode(TINY_PNG).decode()
    with patch("sift.llm.process_image_content", side_effect=_fake_describe()):
        r = CliRunner().invoke(app, ["describe", b64], env=_env())
    assert r.exit_code == 0, r.output


def test_describe_http():
    class FakeResp:
        def __init__(self, data): self._b = io.BytesIO(data)
        def read(self, n): return self._b.read(n)
        def __enter__(self): return self
        def __exit__(self, *a): return False
    with patch("urllib.request.urlopen", return_value=FakeResp(TINY_PNG)), \
         patch("sift.llm.process_image_content", side_effect=_fake_describe()):
        r = CliRunner().invoke(app, ["describe", "http://x/y.png"], env=_env())
    assert r.exit_code == 0, r.output


def test_describe_requires_vlm():
    b64 = base64.b64encode(TINY_PNG).decode()
    r = CliRunner().invoke(app, ["describe", b64], env=_env(vlm=False))
    assert r.exit_code == 2
    assert "VLM" in (r.stderr or r.output)


def test_describe_bad_format(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(b"<html>nope</html>")
    r = CliRunner().invoke(app, ["describe", str(p)], env=_env())
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["success"] is False
    assert "unrecognized" in data["error"]


def test_describe_max_bytes(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(TINY_PNG)
    r = CliRunner().invoke(app, ["describe", str(p), "--max-bytes", "10"], env=_env())
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert "exceeds max size" in data["error"]


def test_describe_llm_failure(tmp_path: Path):
    p = tmp_path / "x.png"
    p.write_bytes(TINY_PNG)
    with patch("sift.llm.process_image_content", side_effect=_fake_describe(description=None, err="VLM processing failed: boom")):
        r = CliRunner().invoke(app, ["describe", str(p)], env=_env())
    # soft-fail on LLM error: exit 0, success=false
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["success"] is False
    assert "boom" in data["error"]
