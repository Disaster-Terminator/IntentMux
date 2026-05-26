from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.build_cloud_runtime import build_cloud_runtime
from scripts.check_cloud_runtime import check_cloud_runtime

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_source_runtime(runtime_home: Path) -> None:
    config_dir = runtime_home / "config"
    bank_dir = runtime_home / "semantic_sets"
    config_dir.mkdir(parents=True)
    bank_dir.mkdir(parents=True)
    (config_dir / "routes.yaml").write_text(
        """
route_model: intentmux
fallback_route_id: lite
route_bank_path: ../semantic_sets/route_bank.yaml
embedding_url: http://127.0.0.1:1234/v1/embeddings
embedding_model: text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0
litellm_base_url: http://127.0.0.1:4000
listen_host: 127.0.0.1
listen_port: 4001
routes:
  lite:
    target_model: lite
    description: low risk
    utterances:
      - hi
  deep:
    target_model: deep
    description: high risk
    utterances:
      - debug this outage
""",
        encoding="utf-8",
    )
    (bank_dir / "route_bank.yaml").write_text(
        """
routes:
  lite:
    utterances:
      - hi
  deep:
    utterances:
      - debug this outage
""",
        encoding="utf-8",
    )
    (runtime_home / "logs" / "prompts").mkdir(parents=True)
    (runtime_home / "logs" / "prompts" / "2026-05-26.jsonl").write_text(
        "private prompt",
        encoding="utf-8",
    )
    (runtime_home / "logs" / "quality").mkdir(parents=True)
    (runtime_home / "logs" / "quality" / "report.md").write_text("private report", encoding="utf-8")
    (config_dir / "routes.yaml.backup-20260526").write_text("backup", encoding="utf-8")


def test_build_cloud_runtime_copies_only_reviewed_assets_and_passes_gate(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "cloud"
    write_source_runtime(source)

    results = build_cloud_runtime(
        source,
        output,
        litellm_base_url="https://litellm.internal",
        embedding_url="https://embedding.internal/v1/embeddings",
    )

    assert all(result.ok for result in results)
    assert sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()) == [
        "config/routes.yaml",
        "semantic_sets/route_bank.yaml",
    ]
    assert all(result.ok for result in check_cloud_runtime(output))
    config = yaml.safe_load((output / "config" / "routes.yaml").read_text(encoding="utf-8"))
    assert config["litellm_base_url"] == "https://litellm.internal"
    assert config["embedding_url"] == "https://embedding.internal/v1/embeddings"
    assert config["listen_host"] == "0.0.0.0"
    assert config["route_bank_path"] == "../semantic_sets/route_bank.yaml"
    assert config["routes"]["lite"]["target_model"] == "lite"
    assert config["routes"]["deep"]["target_model"] == "deep"
    assert not (output / "logs").exists()
    assert not (output / "config" / "routes.yaml.backup-20260526").exists()


def test_build_cloud_runtime_refuses_non_empty_output_without_force(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "cloud"
    write_source_runtime(source)
    output.mkdir()
    (output / "leftover.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="output runtime is not empty"):
        build_cloud_runtime(
            source,
            output,
            litellm_base_url="https://litellm.internal",
            embedding_url="https://embedding.internal/v1/embeddings",
        )


def test_build_cloud_runtime_fails_closed_when_cloud_urls_are_not_provided(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "cloud"
    write_source_runtime(source)

    results = build_cloud_runtime(source, output)

    assert any(result.name == "local_only_hosts" and not result.ok for result in results)


def test_build_cloud_runtime_script_entrypoint_runs_from_file_path(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "cloud"
    write_source_runtime(source)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_cloud_runtime.py"),
            "--source-runtime",
            str(source),
            "--output-runtime",
            str(output),
            "--litellm-base-url",
            "https://litellm.internal",
            "--embedding-url",
            "https://embedding.internal/v1/embeddings",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "PASS\tsecret_like_values\tnone" in result.stdout
