from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request

import pytest

from writer.http_api import create_server
from writer.mcp_server import WriterTools, build_server
from writer.schemas import PieceContract, SchemaError, VoiceSampleContract
from writer.storage import WriterStore


BAD_FIELDS = (
    ({"title": 1}, "piece.title must be a string"),
    ({"dek": []}, "piece.dek must be a string"),
    ({"tags": "ab"}, "piece.tags must be null or a list of strings"),
    ({"tags": ["ok", 1]}, "piece.tags must be null or a list of strings"),
    (
        {"credit_lines": "xy"},
        "piece.credit_lines must be null or a list of strings",
    ),
    (
        {"credit_lines": ["ok", False]},
        "piece.credit_lines must be null or a list of strings",
    ),
    (
        {"voice_sample_ids": "1"},
        "piece.voice_sample_ids must be null or a list of integers",
    ),
    (
        {"voice_sample_ids": [True]},
        "piece.voice_sample_ids must be null or a list of integers",
    ),
    (
        {"voice_sample_ids": ["1"]},
        "piece.voice_sample_ids must be null or a list of integers",
    ),
    (
        {"voice_sample_ids": [1.0]},
        "piece.voice_sample_ids must be null or a list of integers",
    ),
    ({"angle": {}}, "piece.angle must be a string"),
    (
        {"target_length": True},
        "piece.target_length must be null or a positive integer",
    ),
    (
        {"target_length": "60"},
        "piece.target_length must be null or a positive integer",
    ),
    (
        {"target_length": 1.0},
        "piece.target_length must be null or a positive integer",
    ),
    (
        {"target_length": 0},
        "piece.target_length must be null or a positive integer",
    ),
    (
        {"target_length": -1},
        "piece.target_length must be null or a positive integer",
    ),
    ({"scan_voice": "false"}, "piece.scan_voice must be a boolean"),
    ({"scan_voice": 0}, "piece.scan_voice must be a boolean"),
    ({"scan_voice": 1}, "piece.scan_voice must be a boolean"),
    ({"scan_voice": None}, "piece.scan_voice must be a boolean"),
    ({"scan_voice": []}, "piece.scan_voice must be a boolean"),
    ({"scan_voice": {}}, "piece.scan_voice must be a boolean"),
)


@pytest.mark.parametrize(
    ("fields", "field"),
    (
        ({"title": 1}, "title"),
        ({"dek": []}, "dek"),
        ({"tags": "ab"}, "tags"),
        ({"tags": ["ok", 1]}, "tags"),
        ({"credit_lines": "xy"}, "credit_lines"),
        ({"credit_lines": ["ok", False]}, "credit_lines"),
        ({"voice_warnings": "warning"}, "voice_warnings"),
        ({"voice_warnings": [1]}, "voice_warnings"),
        ({"voice_sample_ids": "1"}, "voice_sample_ids"),
        ({"voice_sample_ids": [True]}, "voice_sample_ids"),
        ({"angle": {}}, "angle"),
        ({"target_length": "60"}, "target_length"),
    ),
)
def test_piece_contract_rejects_malformed_persisted_fields(
        fields, field):
    with pytest.raises(
        SchemaError,
        match=rf"^piece\.{field} must be",
    ):
        PieceContract(
            kind="blog",
            body="A measured result.",
            **fields,
        ).validate()


def payload(**fields) -> dict:
    return {
        "kind": "blog",
        "body": "A robust result.",
        **fields,
    }


def add_sample(store: WriterStore) -> None:
    store.add_voice_sample(VoiceSampleContract(
        name="Fixture voice",
        source_type="text",
        raw_text="Name the measured result.",
    ))


@pytest.mark.parametrize(("fields", "error"), BAD_FIELDS)
def test_direct_tool_rejects_malformed_piece_fields(
        tmp_path, fields, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        add_sample(store)
        result = WriterTools(store).save_piece(payload(**fields))

        assert result == {"ok": False, "error": error}
        assert store.entity_counts()["pieces"] == 0
    finally:
        store.close()


def test_valid_piece_fields_round_trip_without_type_drift(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        add_sample(store)
        result = WriterTools(store).save_piece(payload(
            title="Measured",
            dek="One local result.",
            tags=["local", "test"],
            credit_lines=["Source: fixture"],
            voice_sample_ids=[1],
            angle="proof first",
            target_length=60,
            scan_voice=False,
        ))

        assert result["ok"] is True
        saved = result["piece"]
        restored = store.get_piece(saved["id"]).to_dict()
        assert saved == restored
        assert saved["voice_warnings"] == []
    finally:
        store.close()


@pytest.mark.parametrize(
    ("fields", "error"),
    (
        ({"tags": "ab"}, "piece.tags must be null or a list of strings"),
        (
            {"voice_sample_ids": [True]},
            "piece.voice_sample_ids must be null or a list of integers",
        ),
        ({"target_length": "60"},
         "piece.target_length must be null or a positive integer"),
        ({"scan_voice": "false"}, "piece.scan_voice must be a boolean"),
    ),
)
def test_fastmcp_rejects_representative_piece_aliases(
        tmp_path, fields, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        add_sample(store)
        server = build_server(WriterTools(store))

        async def call_tool():
            return await server._tool_manager.call_tool(
                "save_piece",
                {"piece": payload(**fields)},
                convert_result=False,
            )

        assert asyncio.run(call_tool()) == {"ok": False, "error": error}
        assert store.entity_counts()["pieces"] == 0
    finally:
        store.close()


@pytest.fixture
def writer_http(tmp_path):
    server = create_server(
        host="127.0.0.1",
        port=0,
        token="writer-test-token",
        database=tmp_path / "writer.db",
    )
    add_sample(server.store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post_piece(server, body):
    request = urllib.request.Request(
        "http://127.0.0.1:"
        f"{int(server.server_address[1])}/api/writer/v1/pieces",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Writer-Token": "writer-test-token",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@pytest.mark.parametrize(
    ("fields", "error"),
    (
        ({"tags": "ab"}, "piece.tags must be null or a list of strings"),
        (
            {"voice_sample_ids": [True]},
            "piece.voice_sample_ids must be null or a list of integers",
        ),
        ({"target_length": "60"},
         "piece.target_length must be null or a positive integer"),
        ({"scan_voice": "false"}, "piece.scan_voice must be a boolean"),
    ),
)
def test_http_rejects_representative_piece_aliases(
        writer_http, fields, error):
    status, rejected = post_piece(
        writer_http,
        payload(**fields),
    )

    assert status == 400
    assert rejected["error"] == {
        "code": "request_failed",
        "message": error,
    }
    assert writer_http.store.entity_counts()["pieces"] == 0
