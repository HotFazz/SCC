from scc.claude_cli import ClaudeCLIClient


def test_parse_output_handles_successful_stream_json() -> None:
    client = ClaudeCLIClient(executable="claude")
    result = client._parse_output(
        stdout=(
            '{"type":"system","subtype":"init","session_id":"session-1"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Working"}]}}\n'
            '{"type":"result","result":"Done","is_error":false}\n'
        ),
        stderr="",
        return_code=0,
    )
    assert result.ok is True
    assert result.session_id == "session-1"
    assert result.display_text == "Done"


def test_parse_output_handles_error_result() -> None:
    client = ClaudeCLIClient(executable="claude")
    result = client._parse_output(
        stdout=(
            '{"type":"system","subtype":"init","session_id":"session-1"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Not logged in"}]},"error":"authentication_failed"}\n'
            '{"type":"result","result":"Not logged in","is_error":true}\n'
        ),
        stderr="",
        return_code=1,
    )
    assert result.ok is False
    assert result.error == "authentication_failed"
