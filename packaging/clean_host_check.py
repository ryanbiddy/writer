"""Writer S5 gate: wheel -> bare venv -> truthful first run.

The tested commands run from a neutral directory under ``python -P`` with an
isolated WRITER_DATA_DIR and no repository path in PYTHONPATH. The final step
drives the installed MCP server over stdio and successfully calls all 17 tools.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MCP_SMOKE = REPO / "tests" / "mcp_stdio_smoke.py"


def run(
        command: list[str], cwd: Path, env: dict[str, str],
        timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def finish(steps: list[dict], report: Path | None) -> int:
    failed = [step for step in steps if step["status"] == "FAIL"]
    payload = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "steps": steps,
        "failed": len(failed),
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        f"\nWriter clean-host gate: {len(steps)} steps, "
        f"{len(failed)} failed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=None,
        help="write the machine-readable gate record here",
    )
    args = parser.parse_args(argv)
    steps: list[dict] = []

    def record(
            step: str, status: str, detail: str,
            output: str = "") -> None:
        steps.append({
            "step": step,
            "status": status,
            "detail": detail,
            "output_tail": output[-2000:],
        })
        print(f"[{status:>4}] {step}: {detail}")

    with tempfile.TemporaryDirectory(
            prefix="writer-clean-host-") as temporary:
        root = Path(temporary)
        dist = root / "dist"
        build = run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(REPO),
                "--no-deps",
                "-w",
                str(dist),
            ],
            REPO,
            dict(os.environ),
        )
        wheels = list(dist.glob("ryan_writer-*.whl"))
        if build.returncode != 0 or len(wheels) != 1:
            record(
                "build-wheel", "FAIL", "pip wheel failed",
                build.stdout + build.stderr)
            return finish(steps, args.report)
        wheel = wheels[0]
        record("build-wheel", "PASS", wheel.name)

        environment = root / "venv"
        venv.create(environment, with_pip=True)
        bindir = environment / (
            "Scripts" if os.name == "nt" else "bin")
        python = bindir / (
            "python.exe" if os.name == "nt" else "python")
        install = run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--quiet",
                f"ryan-writer[mcp] @ {wheel.as_uri()}",
            ],
            root,
            dict(os.environ),
        )
        if install.returncode != 0:
            record(
                "install-wheel", "FAIL", "pip install failed",
                install.stdout + install.stderr)
            return finish(steps, args.report)
        record(
            "install-wheel", "PASS",
            "wheel plus [mcp] extra installed into a bare venv")

        userland = root / "userland"
        userland.mkdir()
        data_dir = root / "writer-data"
        env = dict(os.environ)
        env["WRITER_DATA_DIR"] = str(data_dir)
        env.pop("WRITER_UOINK_URL", None)
        env.pop("WRITER_UOINK_TOKEN", None)
        env.pop("PYTHONPATH", None)

        def writer(*command: str, timeout: int = 180):
            return run(
                [str(python), "-P", "-m", "writer.cli", *command],
                userland,
                env,
                timeout=timeout,
            )

        imported = run(
            [
                str(python),
                "-P",
                "-c",
                (
                    "import json, pathlib, writer; "
                    "p=pathlib.Path(writer.__file__).resolve(); "
                    "print(json.dumps({'version': writer.__version__, "
                    "'origin': str(p)}))"
                ),
            ],
            userland,
            env,
        )
        try:
            origin = json.loads(imported.stdout)
            installed = (
                imported.returncode == 0
                and origin["version"]
                and not Path(origin["origin"]).is_relative_to(REPO)
            )
        except (KeyError, ValueError, json.JSONDecodeError):
            installed = False
            origin = {}
        record(
            "installed-import",
            "PASS" if installed else "FAIL",
            (
                f"Writer {origin.get('version')} imported outside the repo"
                if installed else "installed import was not isolated"
            ),
            "" if installed else imported.stdout + imported.stderr,
        )

        human = writer("doctor")
        optional_uoink_states = (
            "absent",
            "unconfigured",
            "unhealthy",
        )
        human_ok = (
            human.returncode == 0
            and "READY for local writing" in human.stdout
            and "[ok] database: ready" in human.stdout
            and "[ok] packaged_data: ready" in human.stdout
            and "[ok] mcp: ready" in human.stdout
            and any(
                f"[optional] uoink: {state}" in human.stdout
                for state in optional_uoink_states
            )
        )
        record(
            "doctor",
            "PASS" if human_ok else "FAIL",
            f"exit {human.returncode}; truthful required/optional verdict",
            human.stdout + human.stderr,
        )

        machine = writer("doctor", "--json")
        try:
            doctor_payload = json.loads(machine.stdout)
            checks = {
                check["name"]: check
                for check in doctor_payload["checks"]
            }
            machine_ok = (
                machine.returncode == 0
                and doctor_payload["ok"] is True
                and set(checks) == {
                    "database", "packaged_data", "mcp", "uoink"}
                and checks["database"]["ok"] is True
                and checks["packaged_data"]["ok"] is True
                and checks["mcp"]["status"] == "ready"
                and checks["uoink"]["status"] in optional_uoink_states
                and checks["uoink"]["result"]["contract"]
                == "ryan.suite.peer"
                and checks["uoink"]["result"]["state"]
                == checks["uoink"]["status"]
            )
        except (KeyError, TypeError, json.JSONDecodeError):
            machine_ok = False
            checks = {}
        record(
            "doctor-json",
            "PASS" if machine_ok else "FAIL",
            (
                "required checks ready; optional Uoink peer state explicit"
                if machine_ok else "doctor JSON was incomplete or false"
            ),
            "" if machine_ok else machine.stdout + machine.stderr,
        )

        config = writer("serve-mcp", "--print-config")
        try:
            config_payload = json.loads(config.stdout)
            server = config_payload["mcpServers"]["writer"]
            config_ok = (
                config.returncode == 0
                and Path(server["command"]).resolve() == python.resolve()
                and server["args"] == [
                    "-m", "writer.cli", "serve-mcp"]
            )
        except (KeyError, TypeError, json.JSONDecodeError):
            config_ok = False
        record(
            "mcp-config",
            "PASS" if config_ok else "FAIL",
            (
                "installed interpreter and module entry point emitted"
                if config_ok else "MCP config did not target the clean venv"
            ),
            "" if config_ok else config.stdout + config.stderr,
        )

        smoke = run(
            [
                str(python),
                "-P",
                str(MCP_SMOKE),
                "--data-dir",
                str(data_dir / "mcp-smoke"),
            ],
            userland,
            env,
            timeout=300,
        )
        try:
            smoke_payload = json.loads(smoke.stdout)
            smoke_ok = (
                smoke.returncode == 0
                and smoke_payload["ok"] is True
                and smoke_payload["tool_count"] == 17
                and len(smoke_payload["listed_tools"]) == 17
                and smoke_payload["called_tools"]
                == smoke_payload["listed_tools"]
            )
        except (KeyError, TypeError, json.JSONDecodeError):
            smoke_ok = False
        record(
            "mcp-all-tools",
            "PASS" if smoke_ok else "FAIL",
            (
                "initialize -> tools/list -> all 17 tools/call succeeded"
                if smoke_ok else "black-box MCP smoke failed"
            ),
            "" if smoke_ok else smoke.stdout + smoke.stderr,
        )

    return finish(steps, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
