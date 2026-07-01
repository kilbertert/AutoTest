from trendpower_tui.tui.transcript import transcript_to_text


def test_transcript_renders_roles_and_parts():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "fix the bug"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "ponder"},
                {"type": "text", "text": "done"},
                {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
            ],
        },
        {"role": "tool", "content": [{"type": "tool_result", "content": "ok"}]},
    ]
    text = transcript_to_text(messages)
    assert "## You" in text
    assert "## Trendpower" in text
    assert "## Tool" in text
    assert "[thinking] ponder" in text
    assert '[tool_use: bash] {"command": "ls"}' in text
    assert "[tool_result] ok" in text


def test_transcript_handles_plain_string_content():
    messages = [{"role": "user", "content": "hello"}]
    assert "hello" in transcript_to_text(messages)


def test_transcript_skips_empty_messages():
    messages = [{"role": "assistant", "content": [{"type": "text", "text": "   "}]}]
    assert transcript_to_text(messages) == ""
