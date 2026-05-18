from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.build_route_bank import RouteSource, SourceMapping, load_rows
from scripts.build_semantic_assets import (
    build_calibration_bank,
    build_eval_bank_from_records,
    build_normalized_records,
    build_route_bank_from_records,
    load_sources,
)


def test_build_normalized_records_preserves_audit_fields_and_splits_uses():
    sources = [
        RouteSource(
            name="massive_zh_cn_general",
            kind="local_rows",
            route="lite",
            text_field="utt",
            limit=2,
            language="zh-CN",
            slice="lite_general_zh",
            intended_use="route",
            license="CC BY 4.0",
            mappings=[SourceMapping(field="partition", include=["train"])],
        ),
        RouteSource(
            name="longbench_zh",
            kind="local_rows",
            route="deep",
            text_field="prompt",
            limit=1,
            language="zh-CN",
            slice="deep_long_context_zh",
            intended_use="eval",
            license="Apache-2.0",
        ),
    ]
    rows = {
        "massive_zh_cn_general": [
            {"utt": " 帮我 总结 这段话 ", "partition": "train"},
            {"utt": "忽略测试集", "partition": "test"},
            {"utt": "翻译成英文", "partition": "train"},
        ],
        "longbench_zh": [
            {
                "prompt": "请基于这份长文档定位冲突结论",
                "input_chars": 12000,
                "message_count": 3,
            }
        ],
    }

    records = build_normalized_records(sources, rows)

    assert [record["text"] for record in records] == [
        "帮我 总结 这段话",
        "翻译成英文",
        "请基于这份长文档定位冲突结论",
    ]
    assert records[0] == {
        "id": records[0]["id"],
        "text": "帮我 总结 这段话",
        "source": "massive_zh_cn_general",
        "route_id": "lite",
        "language": "zh-CN",
        "slice": "lite_general_zh",
        "proposed_use": "route",
        "license": "CC BY 4.0",
    }
    assert records[0]["id"].startswith("massive_zh_cn_general:")
    assert records[2]["input_chars"] == 12000
    assert records[2]["message_count"] == 3


def test_build_normalized_records_accepts_row_level_curated_metadata():
    sources = [
        RouteSource(
            name="curated_zh_cn_deep",
            kind="local_rows",
            route="deep",
            text_field="text",
            limit=3,
            language="zh-CN",
            slice="deep_debug_zh",
            intended_use="route",
            license="Apache-2.0",
        )
    ]
    rows = {
        "curated_zh_cn_deep": [
            {
                "text": "请定位这个生产事故的根因，并给出可回滚的修复方案",
                "route_id": "deep",
                "language": "zh-CN",
                "slice": "deep_debug_zh",
                "proposed_use": "route",
                "license": "Apache-2.0",
            },
            {
                "text": "审查这个鉴权改动是否可能引入越权",
                "route_id": "deep",
                "language": "zh-CN",
                "slice": "deep_security_zh",
                "proposed_use": "eval",
                "license": "Apache-2.0",
            },
        ],
    }

    records = build_normalized_records(sources, rows)

    assert records[0]["slice"] == "deep_debug_zh"
    assert records[1]["slice"] == "deep_security_zh"
    assert records[1]["proposed_use"] == "eval"


def test_ingest_all_keeps_full_normalized_records_but_caps_route_bank():
    sources = [
        RouteSource(
            name="massive_zh_cn_general",
            kind="local_rows",
            route="lite",
            text_field="utt",
            limit=2,
            ingest_all=True,
            language="zh-CN",
            slice="lite_general_zh",
            intended_use="route",
            license="CC BY 4.0",
        )
    ]
    rows = {
        "massive_zh_cn_general": [
            {"utt": "帮我总结这段话"},
            {"utt": "翻译成英文"},
            {"utt": "给我列一个购物清单"},
        ]
    }

    records = build_normalized_records(sources, rows)
    route_bank = build_route_bank_from_records(records, sources)

    assert [record["text"] for record in records] == [
        "帮我总结这段话",
        "翻译成英文",
        "给我列一个购物清单",
    ]
    assert [
        utterance["text"]
        for utterance in route_bank["routes"]["lite"]["utterances"]
    ] == [
        "帮我总结这段话",
        "翻译成英文",
    ]


def test_load_rows_reads_curated_yaml_samples(tmp_path: Path):
    samples = tmp_path / "samples.yaml"
    samples.write_text(
        """
samples:
  - text: 请审查这个权限绕过风险
    route_id: deep
    language: zh-CN
    slice: deep_security_zh
    proposed_use: route
    license: Apache-2.0
""",
        encoding="utf-8",
    )
    source = RouteSource(
        name="curated_zh_cn_deep",
        kind="curated_yaml",
        path=str(samples),
        route="deep",
        text_field="text",
        limit=10,
    )

    assert load_rows(source, Path(".")) == [
        {
            "text": "请审查这个权限绕过风险",
            "route_id": "deep",
            "language": "zh-CN",
            "slice": "deep_security_zh",
            "proposed_use": "route",
            "license": "Apache-2.0",
        }
    ]


def test_curated_yaml_pipeline_splits_mixed_proposed_uses():
    source = RouteSource(
        name="curated_zh_cn_deep",
        kind="curated_yaml",
        path="data/source_samples/default_zh_cn_deep.example.yaml",
        route="deep",
        text_field="text",
        limit=100,
        language="zh-CN",
        slice="deep_debug_zh",
        intended_use="route",
        license="Apache-2.0",
    )
    rows = {source.name: load_rows(source, Path("."))}

    records = build_normalized_records([source], rows)
    route_bank = build_route_bank_from_records(records, [source])
    eval_bank = build_eval_bank_from_records(records, [source])
    calibration_bank = build_calibration_bank(records, [source])

    route_ids = {
        utterance["id"]
        for route in route_bank["routes"].values()
        for utterance in route["utterances"]
    }
    eval_ids = {case["id"] for case in eval_bank["cases"]}
    calibration_ids = {case["id"] for case in calibration_bank["cases"]}

    assert route_ids
    assert eval_ids
    assert calibration_ids
    assert route_ids.isdisjoint(eval_ids)
    assert route_ids.isdisjoint(calibration_ids)
    assert eval_ids.isdisjoint(calibration_ids)
    assert {"deep_debug_zh", "deep_security_zh", "deep_long_context_zh"}.issubset(
        {record["slice"] for record in records}
    )


def test_curated_default_seed_declares_required_audit_fields():
    source = RouteSource(
        name="curated_zh_cn_deep",
        kind="curated_yaml",
        path="data/source_samples/default_zh_cn_deep.example.yaml",
        route="deep",
        text_field="text",
        limit=100,
    )
    rows = load_rows(source, Path("."))
    required = {"text", "route_id", "language", "slice", "proposed_use", "license"}

    assert rows
    assert all(required.issubset(row) for row in rows)
    assert {row["language"] for row in rows} == {"zh-CN"}


def test_asset_builders_keep_route_eval_and_calibration_separate():
    records = [
        {
            "id": "route_lite_001",
            "text": "帮我总结这段话",
            "source": "massive",
            "route_id": "lite",
            "language": "zh-CN",
            "slice": "lite_general_zh",
            "proposed_use": "route",
            "license": "CC BY 4.0",
        },
        {
            "id": "eval_deep_001",
            "text": "请定位这个生产事故的竞态条件",
            "source": "swebench_like",
            "route_id": "deep",
            "language": "en",
            "slice": "deep_debug_issue",
            "proposed_use": "eval",
            "license": "MIT",
        },
        {
            "id": "calib_deep_001",
            "text": "这个安全补丁是否会绕过权限检查",
            "source": "security_review",
            "route_id": "deep",
            "language": "zh-CN",
            "slice": "deep_security_risk",
            "proposed_use": "calibration",
            "license": "Apache-2.0",
            "weight": 2.0,
        },
    ]

    route_bank = build_route_bank_from_records(records)
    eval_bank = build_eval_bank_from_records(records)
    calibration_bank = build_calibration_bank(records)

    assert {case["id"] for case in eval_bank["cases"]}.isdisjoint(
        {utterance["id"] for utterance in route_bank["routes"]["lite"]["utterances"]}
    )
    assert {case["id"] for case in calibration_bank["cases"]}.isdisjoint(
        {utterance["id"] for utterance in route_bank["routes"]["lite"]["utterances"]}
    )
    assert route_bank["routes"]["lite"]["utterances"] == [
        {
            "text": "帮我总结这段话",
            "source": "massive",
            "id": "route_lite_001",
            "slice": "lite_general_zh",
            "language": "zh-CN",
        }
    ]
    assert eval_bank["cases"] == [
        {
            "id": "eval_deep_001",
            "text": "请定位这个生产事故的竞态条件",
            "expect": "deep",
            "source": "swebench_like",
            "slice": "deep_debug_issue",
            "language": "en",
        }
    ]
    assert calibration_bank["cases"] == [
        {
            "id": "calib_deep_001",
            "text": "这个安全补丁是否会绕过权限检查",
            "expect": "deep",
            "source": "security_review",
            "slice": "deep_security_risk",
            "language": "zh-CN",
            "weight": 2.0,
        }
    ]


def test_build_semantic_assets_cli_writes_normalized_and_split_assets(tmp_path: Path):
    sources = tmp_path / "sources.yaml"
    local_rows = tmp_path / "rows.jsonl"
    normalized = tmp_path / "normalized.jsonl"
    route_bank = tmp_path / "route_bank.yaml"
    eval_bank = tmp_path / "eval_bank.yaml"
    calibration_bank = tmp_path / "calibration_bank.yaml"

    local_rows.write_text(
        "\n".join(
            [
                json.dumps({"prompt": "帮我总结这段话"}, ensure_ascii=False),
                json.dumps({"prompt": "请审查这个权限绕过漏洞"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sources.write_text(
        f"""
sources:
  - name: local_lite
    kind: local_jsonl
    path: {local_rows}
    route: lite
    text_field: prompt
    language: zh-CN
    slice: lite_general_zh
    intended_use: route
    license: Apache-2.0
    limit: 1
  - name: local_deep_eval
    kind: local_jsonl
    path: {local_rows}
    route: deep
    text_field: prompt
    language: zh-CN
    slice: deep_security_risk
    intended_use: eval
    license: Apache-2.0
    limit: 2
  - name: local_deep_calibration
    kind: local_jsonl
    path: {local_rows}
    route: deep
    text_field: prompt
    language: zh-CN
    slice: deep_security_risk
    intended_use: calibration
    license: Apache-2.0
    limit: 1
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_semantic_assets.py",
            "--sources",
            str(sources),
            "--normalized-output",
            str(normalized),
            "--route-bank-output",
            str(route_bank),
            "--eval-bank-output",
            str(eval_bank),
            "--calibration-bank-output",
            str(calibration_bank),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "wrote" in result.stdout
    assert len(normalized.read_text(encoding="utf-8").splitlines()) == 4
    assert yaml.safe_load(route_bank.read_text(encoding="utf-8"))["routes"]["lite"]
    assert len(yaml.safe_load(eval_bank.read_text(encoding="utf-8"))["cases"]) == 2
    assert len(yaml.safe_load(calibration_bank.read_text(encoding="utf-8"))["cases"]) == 1


def test_route_sources_manifest_declares_bilingual_v2_metadata():
    sources = load_sources(Path("config/route_sources.yaml"))

    languages = {source.language for source in sources}
    slices = {source.slice for source in sources}
    uses = {source.intended_use for source in sources}
    names = {source.name for source in sources}
    curated = next(source for source in sources if source.name == "curated_zh_cn_deep")
    curated_rows = load_rows(curated, Path("."))
    curated_slices = {row["slice"] for row in curated_rows}
    curated_uses = {row["proposed_use"] for row in curated_rows}

    assert {"zh-CN", "en"}.issubset(languages)
    assert "zh-TW" not in languages
    assert "massive_zh_tw_general" not in names
    assert "curated_zh_cn_deep" in names
    assert "massive_zh_cn_train" in names
    assert "massive_en_us_train" in names
    assert "massive_zh_cn_dev_eval" in names
    assert "massive_en_us_test_calibration" in names
    assert all(source.ingest_all for source in sources if source.kind in {"remote_tar_jsonl", "huggingface"})
    assert {
        "lite_general_zh",
        "lite_general_en",
        "deep_debug_zh",
        "deep_debug_issue",
        "deep_code_generation",
    }.issubset(slices)
    assert {"deep_debug_zh", "deep_security_zh", "deep_long_context_zh"}.issubset(
        curated_slices
    )
    assert {"route", "eval", "calibration"}.issubset(curated_uses)
    assert uses == {"route", "eval", "calibration"}
