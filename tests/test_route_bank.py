from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import yaml

from scripts.build_route_bank import (
    RouteSource,
    SourceMapping,
    build_route_bank,
    load_rows,
    load_sources,
    normalize_text,
)


def test_normalize_text_compacts_whitespace_and_truncates():
    text = "  # hello\n\n<!-- hidden issue template -->world  " + "x" * 500

    normalized = normalize_text(text, max_chars=20)

    assert normalized == "hello world xxxxxxxx"


def test_build_route_bank_maps_rows_to_routes_and_keeps_sources():
    sources = [
        RouteSource(
            name="massive_zh_cn_general",
            kind="local_rows",
            route="lite",
            text_field="utt",
            limit=2,
            homepage="https://www.amazon.science/code-and-datasets/massive",
            license="CC BY 4.0",
            license_url="https://github.com/alexa/massive/blob/master/LICENSE",
            mappings=[
                SourceMapping(field="domain", include=["general", "qa"]),
            ],
        ),
        RouteSource(
            name="swebench_issue_resolution",
            kind="local_rows",
            route="deep",
            text_field="problem_statement",
            limit=1,
        ),
    ]
    rows = {
        "massive_zh_cn_general": [
            {"utt": " 翻译 成 中文 ", "domain": "general"},
            {"utt": "播放音乐", "domain": "music"},
            {"utt": "总结这篇文章", "domain": "qa"},
        ],
        "swebench_issue_resolution": [
            {"problem_statement": "Fix crash when parsing config files."},
            {"problem_statement": "Second issue should be limited out."},
        ],
    }

    bank = build_route_bank(sources, rows)

    assert bank["generated"]["tool"] == "scripts/build_route_bank.py"
    assert bank["generated"]["commit"]
    assert bank["generated"]["generated_at"]
    assert bank["generated"]["source_manifest_sha256"]
    assert bank["generated"]["source_row_counts"] == {
        "massive_zh_cn_general": 3,
        "swebench_issue_resolution": 2,
    }
    assert bank["sources"][0] == {
        "name": "massive_zh_cn_general",
        "kind": "local_rows",
        "route": "lite",
        "limit": 2,
        "ingest_all": False,
        "url": None,
        "dataset": None,
        "split": None,
        "homepage": "https://www.amazon.science/code-and-datasets/massive",
        "license": "CC BY 4.0",
        "license_url": "https://github.com/alexa/massive/blob/master/LICENSE",
    }
    assert bank["routes"]["lite"]["utterances"] == [
        {
            "text": "翻译 成 中文",
            "source": "massive_zh_cn_general",
        },
        {
            "text": "总结这篇文章",
            "source": "massive_zh_cn_general",
        },
    ]
    assert bank["routes"]["deep"]["utterances"] == [
        {
            "text": "Fix crash when parsing config files.",
            "source": "swebench_issue_resolution",
        }
    ]


def test_legacy_route_bank_builder_skips_non_route_records():
    sources = [
        RouteSource(
            name="mixed_curated",
            kind="local_rows",
            route="deep",
            text_field="text",
            limit=10,
        ),
        RouteSource(
            name="eval_only",
            kind="local_rows",
            route="deep",
            text_field="text",
            limit=10,
            intended_use="eval",
        ),
    ]
    rows = {
        "mixed_curated": [
            {"text": "进入在线 route bank", "proposed_use": "route"},
            {"text": "只能进入 eval bank", "proposed_use": "eval"},
            {"text": "只能进入 calibration bank", "proposed_use": "calibration"},
        ],
        "eval_only": [
            {"text": "source 级 eval 也不能进 route bank"},
        ],
    }

    bank = build_route_bank(sources, rows)

    assert bank["routes"]["deep"]["utterances"] == [
        {"text": "进入在线 route bank", "source": "mixed_curated"}
    ]


def test_route_sources_manifest_loads_mature_sources():
    sources = load_sources(Path("config/route_sources.yaml"))

    names = {source.name for source in sources}

    assert "massive_zh_cn_train" in names
    assert "massive_zh_cn_dev_eval" in names
    assert "swebench_issue_resolution" in names
    assert "mbpp_codegen" in names
    assert "humaneval_codegen" in names
    assert all(source.homepage for source in sources)
    assert all(source.license for source in sources)
    assert all(source.license_url for source in sources)


def test_tracked_example_route_bank_is_small_and_auditable():
    sample_path = Path("examples/route_bank.sample.yaml")
    assert sample_path.exists()

    payload = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert payload["generated"]["tool"] == "scripts/build_route_bank.py"
    assert payload["generated"]["commit"]
    assert payload["generated"]["source_manifest_sha256"]
    assert payload["sources"]
    assert set(payload["routes"]) == {"lite", "deep"}
    for source in payload["sources"]:
        assert source["name"]
        assert source["homepage"]
        assert source["license"]
        assert source["license_url"]
    for route_payload in payload["routes"].values():
        assert 1 <= len(route_payload["utterances"]) <= 12
        for utterance in route_payload["utterances"]:
            assert utterance["text"]
            assert utterance["source"]


def test_load_rows_reads_remote_tar_jsonl_from_cache(tmp_path):
    archive_path = tmp_path / "data" / "downloads" / "sample.tar.gz"
    archive_path.parent.mkdir(parents=True)
    payload = "\n".join(
        [
            json.dumps({"utt": "你好", "partition": "train"}, ensure_ascii=False),
            json.dumps({"utt": "再见", "partition": "test"}, ensure_ascii=False),
        ]
    ).encode("utf-8")
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("data/zh-CN.jsonl")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    rows = load_rows(
        RouteSource(
            name="sample",
            kind="remote_tar_jsonl",
            route="lite",
            text_field="utt",
            limit=10,
            url="https://example.com/sample.tar.gz",
            member="data/zh-CN.jsonl",
        ),
        tmp_path,
    )

    assert rows == [
        {"utt": "你好", "partition": "train"},
        {"utt": "再见", "partition": "test"},
    ]
