from __future__ import annotations

from pathlib import Path

from router.config import load_settings


def test_load_settings_merges_seed_utterances_with_route_bank(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    bank_path = tmp_path / "route_bank.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: cheap-router
threshold: 0.55
margin: 0.04
route_bank_path: route_bank.yaml
routes:
  cheap-router:
    description: seed cheap
    utterances:
      - seed cheap utterance
  pro-router:
    description: seed pro
    utterances:
      - seed pro utterance
""",
        encoding="utf-8",
    )
    bank_path.write_text(
        """
version: 1
routes:
  cheap-router:
    utterances:
      - text: generated cheap utterance
        source: massive_zh_cn_general
      - text: seed cheap utterance
        source: duplicate
  pro-router:
    utterances:
      - text: generated pro utterance
        source: swebench_issue_resolution
  free-probe-router:
    utterances:
      - text: generated probe utterance
        source: local_model_probe
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.routes["cheap-router"].utterances == [
        "seed cheap utterance",
        "generated cheap utterance",
    ]
    assert settings.routes["pro-router"].utterances == [
        "seed pro utterance",
        "generated pro utterance",
    ]
    assert settings.routes["free-probe-router"].utterances == [
        "generated probe utterance",
    ]


def test_load_settings_ignores_missing_route_bank_by_default(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: cheap-router
route_bank_path: missing.yaml
routes:
  cheap-router:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.routes["cheap-router"].utterances == ["seed cheap utterance"]


def test_load_settings_resolves_route_bank_from_cwd_when_not_next_to_config(
    tmp_path: Path,
    monkeypatch,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data" / "semantic_sets"
    data_dir.mkdir(parents=True)
    routes_path = config_dir / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: cheap-router
route_bank_path: data/semantic_sets/route_bank.yaml
routes:
  cheap-router:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    (data_dir / "route_bank.yaml").write_text(
        """
version: 1
routes:
  cheap-router:
    utterances:
      - text: generated cheap utterance
        source: cwd_bank
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings(routes_path)

    assert settings.routes["cheap-router"].utterances == [
        "seed cheap utterance",
        "generated cheap utterance",
    ]
