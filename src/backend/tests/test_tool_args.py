from app.agents.director.chat_orchestrator import _claims_pending_tool, _native_reply
from app.agents.director.tool_args import coerce_jsonish, coerce_tool_args


def test_coerce_nested_shot_json_string():
    args = {
        "expected_script_hash": "abc",
        "shot": '{"scene_id":"dungeon","title":"The Threshold","script_beat":"Wendy enters.","duration_s":4}',
    }
    parsed = coerce_tool_args(args)
    assert parsed["shot"]["title"] == "The Threshold"
    assert parsed["shot"]["duration_s"] == 4


def test_native_reply_parses_string_arguments():
    content, thinking, tools = _native_reply(
        {
            "content": "",
            "thinking": "",
            "tool_calls": [
                {
                    "name": "append_shot",
                    "arguments": '{"expected_script_hash":"abc","shot":{"title":"Wave","duration_s":4}}',
                }
            ],
        }
    )
    assert tools[0]["name"] == "append_shot"
    assert tools[0]["args"]["shot"]["title"] == "Wave"


def test_claims_pending_write_prompt():
    assert _claims_pending_tool("I'll call write_prompt for shot index 1 now.")
    assert _claims_pending_tool("I will call append_shot now.")
    assert not _claims_pending_tool("The prompt is already written.")
