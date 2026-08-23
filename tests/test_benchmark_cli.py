from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from test_benchmark import config, formal_profile
from test_metrics import literal_rows

from hy3_algotrace.artifacts import canonical_json_bytes
from hy3_algotrace.benchmark_cli import main
from hy3_algotrace.benchmark_models import ObservationReplayInput
from hy3_algotrace.hy3_client import Hy3AttemptContext


def write_json(path: Path, payload: object) -> None:
    path.write_bytes(canonical_json_bytes(payload))


def test_validate_config_cli_emits_literal_machine_readable_identity(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    config_path = tmp_path / "config.json"
    write_json(config_path, config().model_dump(mode="json"))

    result = main(["validate-config", "--config", str(config_path)])

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "benchmark_id": "bench-1",
        "formal": False,
        "remote_attempt_budget": 4,
        "static_attempt_lower_bound": 4,
        "valid": True,
    }


def test_run_cli_uses_injected_executor_and_immutable_artifact_tree(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    benchmark_config = config(
        benchmark_id="cli-run",
        sample_ids=("n1",),
        audit_ids=("n1",),
        budget=2,
    )
    config_path = tmp_path / "config.json"
    artifact_root = tmp_path / "artifacts"
    write_json(config_path, benchmark_config.model_dump(mode="json"))
    row = {item.sample_id: item for item in literal_rows()}["n1"]

    def execute(
        sample_id: str, observer: Callable[[Hy3AttemptContext], None]
    ):
        observer(
            Hy3AttemptContext(
                operation="logic-reviewer-v1", phase="request", retry_number=1
            )
        )
        observer(
            Hy3AttemptContext(
                operation="adversarial-reviewer-v1", phase="request", retry_number=1
            )
        )
        return row

    result = main(
        [
            "run",
            "--config",
            str(config_path),
            "--artifact-root",
            str(artifact_root),
        ],
        execute=execute,
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "benchmark_id": "cli-run",
        "complete": True,
        "execution_kind": "live",
        "formal_eligible": False,
        "remote_attempts_used": 2,
        "status": "complete",
    }
    assert (artifact_root / "benchmarks/cli-run/report.json").is_file()
    assert (artifact_root / "benchmarks/cli-run/ledger/000001.json").is_file()
    assert (artifact_root / "benchmarks/cli-run/ledger/000002.json").is_file()


def test_replay_cli_is_executable_through_real_module_boundary(tmp_path: Path) -> None:
    benchmark_config = config(
        benchmark_id="shell-replay",
        sample_ids=("n1",),
        audit_ids=("n1",),
        budget=2,
    )
    config_path = tmp_path / "config.json"
    observations_path = tmp_path / "observations.json"
    artifact_root = tmp_path / "artifacts"
    write_json(config_path, benchmark_config.model_dump(mode="json"))
    write_json(
        observations_path,
        ObservationReplayInput(observations=(literal_rows()[0],)).model_dump(mode="json"),
    )
    source_root = Path(__file__).parents[1] / "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hy3_algotrace.benchmark_cli",
            "replay",
            "--config",
            str(config_path),
            "--observations",
            str(observations_path),
            "--artifact-root",
            str(artifact_root),
        ],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "PYTHONPATH": str(source_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "benchmark_id": "shell-replay",
        "complete": True,
        "execution_kind": "artifact_replay",
        "formal_eligible": False,
        "remote_attempts_used": 0,
        "status": "complete",
    }
    assert (artifact_root / "benchmarks/shell-replay/replay-input.json").is_file()
    report = json.loads(
        (artifact_root / "benchmarks/shell-replay/report.json").read_text()
    )
    assert report["execution_kind"] == "artifact_replay"
    assert report["formal_eligible"] is False


def test_shell_modes_fail_closed_without_live_adapter_or_for_formal_replay(
    tmp_path: Path,
) -> None:
    nonformal_path = tmp_path / "nonformal.json"
    write_json(nonformal_path, config().model_dump(mode="json"))
    with pytest.raises(SystemExit):
        main(
            [
                "run",
                "--config",
                str(nonformal_path),
                "--artifact-root",
                str(tmp_path / "no-live-artifacts"),
            ]
        )
    assert not (tmp_path / "no-live-artifacts").exists()

    formal, rows = formal_profile(benchmark_id="formal-replay-denied")
    formal_path = tmp_path / "formal.json"
    observations_path = tmp_path / "formal-observations.json"
    write_json(formal_path, formal.model_dump(mode="json"))
    write_json(
        observations_path,
        ObservationReplayInput(observations=rows).model_dump(mode="json"),
    )
    with pytest.raises(SystemExit):
        main(
            [
                "replay",
                "--config",
                str(formal_path),
                "--observations",
                str(observations_path),
                "--artifact-root",
                str(tmp_path / "no-formal-replay-artifacts"),
            ]
        )
    assert not (tmp_path / "no-formal-replay-artifacts").exists()
