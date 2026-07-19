"""Black-box C-01-style smoke for every Writer MCP tool.

This file intentionally imports only the standard library. The clean-host
gate executes it with the pristine venv's ``python -P`` from a neutral working
directory, so the server can only come from the installed wheel.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

TIMEOUT = 60
EXPECTED_TOOLS = (
    "prepare_draft",
    "save_draft",
    "get_draft",
    "save_piece",
    "list_pieces",
    "validate_composition",
    "prepare_script",
    "save_script",
    "critique_script",
    "revise_script",
    "derive_shot_list",
    "export_shot_list",
    "add_voice_sample",
    "list_voice_samples",
    "remove_voice_sample",
    "scan_voice",
    "writer_status",
)


class StdioClient:
    def __init__(self, env: dict[str, str]):
        self.proc = subprocess.Popen(
            [sys.executable, "-P", "-m", "writer.cli", "serve-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 0
        threading.Thread(
            target=self._pump_stdout, daemon=True).start()
        threading.Thread(
            target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._lines.put(line)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line)

    def send(
            self, method: str, params: dict | None = None,
            *, notify: bool = False) -> dict | None:
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params
        if not notify:
            self._next_id += 1
            message["id"] = self._next_id
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        return self._read_response(self._next_id)

    def _read_response(self, wanted: int) -> dict:
        while True:
            try:
                line = self._lines.get(timeout=TIMEOUT)
            except queue.Empty:
                stderr = "".join(self._stderr[-30:])
                raise RuntimeError(
                    f"no response for id={wanted} within {TIMEOUT}s; "
                    f"server stderr:\n{stderr}"
                ) from None
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"server wrote non-JSON stdout: {line!r}") from exc
            if message.get("id") != wanted:
                continue
            if "error" in message:
                raise RuntimeError(
                    f"protocol error for id={wanted}: {message['error']}")
            return message["result"]

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        if self.proc.returncode not in (0, None):
            stderr = "".join(self._stderr[-30:])
            raise RuntimeError(
                f"Writer MCP server exited {self.proc.returncode}: "
                f"{stderr}")


def _payload(result: dict | None, tool: str) -> dict:
    if not isinstance(result, dict):
        raise RuntimeError(f"{tool} returned no MCP result")
    if result.get("isError") is True:
        raise RuntimeError(f"{tool} returned an MCP error: {result}")
    blocks = [
        block.get("text", "")
        for block in result.get("content", [])
        if block.get("type") == "text"
    ]
    if not blocks:
        raise RuntimeError(f"{tool} returned no text content")
    try:
        payload = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{tool} returned non-JSON text: {blocks[0]!r}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{tool} returned a non-object payload")
    if payload.get("ok") is not True:
        raise RuntimeError(
            f"{tool} did not succeed: {payload.get('error', payload)}")
    return payload


def run_smoke(data_dir: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["WRITER_DATA_DIR"] = str(data_dir)
    env.pop("WRITER_UOINK_URL", None)
    env.pop("WRITER_UOINK_TOKEN", None)
    env.pop("PYTHONPATH", None)
    client = StdioClient(env)
    called: list[str] = []

    def call(name: str, arguments: dict | None = None) -> dict:
        payload = _payload(client.send(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        ), name)
        called.append(name)
        return payload

    try:
        initialized = client.send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "writer-clean-host-smoke",
                    "version": "1",
                },
            },
        )
        if initialized["serverInfo"]["name"] != "writer":
            raise RuntimeError(
                f"unexpected server identity: {initialized['serverInfo']}")
        client.send(
            "notifications/initialized", {}, notify=True)

        listed = client.send("tools/list", {})["tools"]
        names = tuple(tool["name"] for tool in listed)
        if set(names) != set(EXPECTED_TOOLS) or len(names) != 17:
            raise RuntimeError(
                f"unexpected tool surface: {sorted(names)}")
        missing_descriptions = [
            tool["name"] for tool in listed
            if not str(tool.get("description") or "").strip()
        ]
        if missing_descriptions:
            raise RuntimeError(
                "tools missing descriptions: "
                + ", ".join(missing_descriptions))

        call("prepare_draft", {
            "kind": "newsletter",
            "brief": "Black-box install smoke.",
            "draft_text": "A local draft.",
        })
        draft = call("save_draft", {
            "draft": {
                "kind": "newsletter",
                "body": "A local draft.",
            },
        })
        draft_id = int(draft["draft"]["id"])
        call("get_draft", {"draft_id": draft_id})
        call("save_piece", {
            "piece": {
                "kind": "newsletter",
                "body": "A finished local piece.",
            },
        })
        call("list_pieces")
        call("validate_composition", {
            "kind": "newsletter",
            "blocks": ["A finished local piece."],
        })
        call("prepare_script", {
            "brief": "Write a short local test script.",
        })
        script = call("save_script", {
            "script": {
                "hook": "This is the clean-host test.",
                "format": "talking_head",
                "body": "One complete test beat.",
                "beats": [{
                    "label": "proof",
                    "content": "Show the local result.",
                }],
            },
        })
        script_id = int(script["script"]["id"])
        critique = call("critique_script", {
            "script_id": script_id,
            "findings": {"pacing": "The test is concise."},
        })
        call("revise_script", {
            "script_id": script_id,
            "critique_id": int(critique["critique"]["id"]),
        })
        derived = call(
            "derive_shot_list", {"script_id": script_id})
        derived_id = int(derived["script"]["id"])
        output = data_dir / "writer-smoke-shot-list.md"
        call("export_shot_list", {
            "script_id": derived_id,
            "output": str(output),
            "title": "Clean-host smoke",
        })
        if not output.is_file():
            raise RuntimeError(
                "export_shot_list reported success without a file")
        sample = call("add_voice_sample", {
            "sample": {
                "name": "Clean-host voice",
                "source_type": "text",
                "raw_text": "Write plainly and keep the claim specific.",
            },
        })
        sample_id = int(sample["voice_sample"]["id"])
        call("list_voice_samples")
        call("remove_voice_sample", {"sample_id": sample_id})
        call("scan_voice", {
            "text": "This local smoke test names what it proved.",
        })
        status = call("writer_status")
        if status["counts"] != {
                "drafts": 1,
                "pieces": 1,
                "scripts": 2,
                "voice_samples": 0}:
            raise RuntimeError(
                f"unexpected final counts: {status['counts']}")
        if tuple(called) != EXPECTED_TOOLS:
            raise RuntimeError(
                f"tool calls drifted: {called}")
        return {
            "ok": True,
            "server": initialized["serverInfo"],
            "listed_tools": list(names),
            "called_tools": called,
            "tool_count": len(called),
            "errors": [],
        }
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_smoke(args.data_dir)
    except Exception as exc:
        report = {
            "ok": False,
            "server": {},
            "listed_tools": [],
            "called_tools": [],
            "tool_count": 0,
            "errors": [str(exc)],
        }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
