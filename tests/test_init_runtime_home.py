from __future__ import annotations

from pathlib import Path

from scripts.init_runtime_home import main


def test_init_runtime_home_copies_template_without_overwriting(tmp_path: Path):
    template = tmp_path / "template"
    runtime_home = tmp_path / ".intentmux-home"
    (template / "config").mkdir(parents=True)
    (template / "semantic_sets").mkdir()
    (template / "config" / "routes.yaml").write_text("template\n", encoding="utf-8")
    (template / "semantic_sets" / "route_bank.yaml").write_text(
        "bank\n",
        encoding="utf-8",
    )

    assert main(["--template", str(template), "--runtime-home", str(runtime_home)]) == 0
    (runtime_home / "config" / "routes.yaml").write_text("local\n", encoding="utf-8")
    assert main(["--template", str(template), "--runtime-home", str(runtime_home)]) == 0

    assert (runtime_home / "config" / "routes.yaml").read_text(encoding="utf-8") == "local\n"
    assert (runtime_home / "semantic_sets" / "route_bank.yaml").exists()
    assert (runtime_home / "logs" / "routes").is_dir()
    assert (runtime_home / "logs" / "prompts").is_dir()
    assert (runtime_home / "logs" / "health").is_dir()
    assert (runtime_home / "logs" / "quality").is_dir()
    assert (runtime_home / "reviews").is_dir()
    assert (runtime_home / "cache").is_dir()
