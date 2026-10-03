from pathlib import Path

import pytest

from local_genai_mcp.config import PROJECT_ROOT, load_config


def test_example_config_loads():
    config = load_config(PROJECT_ROOT / "config.example.toml")
    assert config.ollama.base_url == "http://192.168.0.10:11434"
    assert config.forge.defaults.width == 1024
    assert config.forge.output_path == Path("~/ai-studio/repo/genai-outputs/forge").expanduser()


def test_trailing_slash_is_removed(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[ollama]\nbase_url = "http://host:11434/"\n[forge]\nbase_url = "http://host:7860/"\n', encoding="utf-8")
    config = load_config(path)
    assert config.ollama.base_url == "http://host:11434"
    assert config.forge.base_url == "http://host:7860"


def test_unknown_key_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[forge]\nbase_ur = "http://host:7860"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="base_ur"):
        load_config(path)


def test_env_var_config_path(tmp_path, monkeypatch):
    path = tmp_path / "my.toml"
    path.write_text('[ollama]\ndefault_model = "qwen3:14b"\n', encoding="utf-8")
    monkeypatch.setenv("LOCAL_GENAI_MCP_CONFIG", str(path))
    assert load_config().ollama.default_model == "qwen3:14b"
