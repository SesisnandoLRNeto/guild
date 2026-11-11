"""The reaper's log rule: a tool call with no result is busy, a replayed request row is not.

Runs under pytest (python3 -m pytest -q test -k reaper) or on its own (python3 test/reaper_test.py).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import reaper   # noqa: E402


def row(kind, block):
    return json.dumps({"type": kind, "message": {"content": [block]}})


def tool_use(tid):
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {}}


def tool_result(tid):
    return {"type": "tool_result", "tool_use_id": tid, "content": "ok"}


def test_replayed_tool_use_in_blob_row_is_not_pending():
    # an old tool_use replayed in an api-request-blob row, its result before the tail: not busy
    tail = [row("api-request-blob", tool_use("toolu_old"))]
    assert reaper.pending_tool_calls(tail) == set()


def test_real_assistant_tool_use_without_result_is_pending():
    tail = [row("assistant", tool_use("toolu_live"))]
    assert reaper.pending_tool_calls(tail) == {"toolu_live"}


def test_result_in_user_row_answers_the_call():
    tail = [row("assistant", tool_use("toolu_a")), row("user", tool_result("toolu_a"))]
    assert reaper.pending_tool_calls(tail) == set()


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   " + name)
            except AssertionError:
                failed += 1
                print("FAIL " + name)
    sys.exit(1 if failed else 0)
