from sift import pretty


def test_pretty_not_json():
    d = {
        "query": "hello",
        "number_of_results": 1,
        "elapsed_seconds": 0.01,
        "results": [{"title": "T", "url": "U", "content": "C", "engine": "wikipedia"}],
        "answers": [],
        "infoboxes": [],
        "suggestions": [],
        "corrections": [],
        "unresponsive_engines": [],
    }
    out = pretty.render(d)
    import json
    try:
        json.loads(out)
        raise AssertionError("pretty output must not be JSON")
    except json.JSONDecodeError:
        pass
    assert "T" in out
    assert "U" in out
