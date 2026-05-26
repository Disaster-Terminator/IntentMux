from __future__ import annotations

from pathlib import Path

from scripts.check_cloud_runtime import check_cloud_runtime


def write_minimal_runtime(runtime_home: Path) -> None:
    config_dir = runtime_home / "config"
    bank_dir = runtime_home / "semantic_sets"
    config_dir.mkdir(parents=True)
    bank_dir.mkdir(parents=True)
    (config_dir / "routes.yaml").write_text(
        """
route_model: intentmux
fallback_route_id: lite
route_bank_path: ../semantic_sets/route_bank.yaml
embedding_url: https://embedding.example/v1/embeddings
litellm_base_url: https://litellm.example
routes:
  lite:
    target_model: lite
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    (bank_dir / "route_bank.yaml").write_text(
        """
routes:
  lite:
    utterances:
      - hi
""",
        encoding="utf-8",
    )


def test_check_cloud_runtime_accepts_minimal_reviewed_runtime(tmp_path: Path):
    write_minimal_runtime(tmp_path)

    results = check_cloud_runtime(tmp_path)

    assert all(result.ok for result in results)


def test_check_cloud_runtime_rejects_private_prompt_logs(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    prompt_dir = tmp_path / "logs" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "2026-05-26.jsonl").write_text("do not read me", encoding="utf-8")

    results = check_cloud_runtime(tmp_path)

    assert any(
        result.name == "forbidden_runtime_artifacts"
        and "logs/prompts/2026-05-26.jsonl" in result.detail
        for result in results
        if not result.ok
    )


def test_check_cloud_runtime_rejects_dot_env_files(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    (tmp_path / ".env").write_text("API_" + "KEY=do-not-ship-this", encoding="utf-8")

    results = check_cloud_runtime(tmp_path)

    assert any(
        result.name == "forbidden_runtime_artifacts" and ".env" in result.detail
        for result in results
        if not result.ok
    )


def test_check_cloud_runtime_rejects_secrets_in_route_bank(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    route_token = "sk-" + ("a" * 24)
    (tmp_path / "semantic_sets" / "route_bank.yaml").write_text(
        f"routes:\n  lite:\n    utterances:\n      - leaked {route_token}\n",
        encoding="utf-8",
    )

    results = check_cloud_runtime(tmp_path)

    assert any(
        result.name == "secret_like_values"
        and "semantic_sets/route_bank.yaml:4" in result.detail
        for result in results
        if not result.ok
    )


def test_check_cloud_runtime_allows_localhost_text_inside_route_bank_examples(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    (tmp_path / "semantic_sets" / "route_bank.yaml").write_text(
        "routes:\n  deep:\n    utterances:\n      - debug localhost callback on 127.0.0.1\n",
        encoding="utf-8",
    )

    results = check_cloud_runtime(tmp_path)

    assert all(result.ok for result in results)


def test_check_cloud_runtime_uses_configured_route_bank_path(tmp_path: Path):
    config_dir = tmp_path / "config"
    bank_dir = tmp_path / "assets"
    config_dir.mkdir(parents=True)
    bank_dir.mkdir(parents=True)
    (config_dir / "routes.yaml").write_text(
        """
route_model: intentmux
fallback_route_id: lite
route_bank_path: ../assets/cloud-bank.yaml
embedding_url: https://embedding.example/v1/embeddings
litellm_base_url: https://litellm.example
routes:
  lite:
    target_model: lite
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    (bank_dir / "cloud-bank.yaml").write_text(
        """
routes:
  lite:
    utterances:
      - hi
""",
        encoding="utf-8",
    )

    results = check_cloud_runtime(tmp_path)

    assert all(result.ok for result in results)


def test_check_cloud_runtime_rejects_route_bank_outside_runtime(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    outside = tmp_path.parent / "outside-route-bank.yaml"
    outside.write_text("routes: {}\n", encoding="utf-8")
    routes_path = tmp_path / "config" / "routes.yaml"
    config = routes_path.read_text(encoding="utf-8").replace(
        "../semantic_sets/route_bank.yaml",
        str(outside),
    )
    routes_path.write_text(config, encoding="utf-8")

    results = check_cloud_runtime(tmp_path)

    assert any(result.name == "route_bank_inside_runtime" and not result.ok for result in results)


def test_check_cloud_runtime_rejects_symlink_pointing_outside_runtime(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "semantic_sets" / "outside-link.txt").symlink_to(outside)

    results = check_cloud_runtime(tmp_path)

    assert any(
        result.name == "unsafe_symlinks" and "semantic_sets/outside-link.txt" in result.detail
        for result in results
        if not result.ok
    )


def test_check_cloud_runtime_rejects_local_only_hosts(tmp_path: Path):
    write_minimal_runtime(tmp_path)
    routes_path = tmp_path / "config" / "routes.yaml"
    routes_path.write_text(
        routes_path.read_text(encoding="utf-8").replace(
            "https://embedding.example/v1/embeddings",
            "http://host.docker.internal:1234/v1/embeddings",
        ),
        encoding="utf-8",
    )

    results = check_cloud_runtime(tmp_path)

    assert any(
        result.name == "local_only_hosts" and "host.docker.internal" in result.detail
        for result in results
        if not result.ok
    )
