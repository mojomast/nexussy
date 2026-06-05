import pytest

from nexussy_textual.client import CoreClient, CoreClientError, parse_envelope, parse_sse_frame


def test_parse_sse_validates_id_and_event():
    frame = parse_sse_frame('id: e1\nevent: done\ndata: {"event_id":"e1","type":"done","payload":{}}\n')
    assert parse_envelope(frame)["type"] == "done"
    with pytest.raises(CoreClientError):
        parse_envelope({"id": "bad", "event": "done", "data": '{"event_id":"e1","type":"done","payload":{}}'})


def test_client_headers_include_api_key_without_printing_value():
    client = CoreClient(api_key="secret-value")
    try:
        assert client.headers()["X-API-Key"] == "secret-value"
    finally:
        import asyncio

        asyncio.run(client.close())
