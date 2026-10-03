import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_ENV_VAR = "LOCAL_GENAI_MCP_CONFIG"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class OllamaConfig:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:11434"
    default_model: str = ""
    timeout_seconds: float = 300
    keep_alive: str = ""
    think: bool = False


@dataclass
class ForgeDefaults:
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 25
    cfg_scale: float = 7.0
    sampler_name: str = "Euler a"
    scheduler: str = ""
    enable_hr: bool = False
    hr_scale: float = 2.0
    hr_upscaler: str = "ESRGAN_4x"
    denoising_strength: float = 0.4
    hr_second_pass_steps: int = 0


@dataclass
class ForgeConfig:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:7860"
    username: str = ""
    password: str = ""
    timeout_seconds: float = 600
    output_dir: str = "~/ai-studio/repo/genai-outputs/forge"
    preview: bool = True
    preview_max_size: int = 512
    defaults: ForgeDefaults = field(default_factory=ForgeDefaults)

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir).expanduser()


@dataclass
class Config:
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    forge: ForgeConfig = field(default_factory=ForgeConfig)
    source: Path | None = None


def candidate_paths() -> list[Path]:
    paths = []
    if env := os.environ.get(CONFIG_ENV_VAR):
        paths.append(Path(env).expanduser())
    paths.append(PROJECT_ROOT / "config.toml")
    paths.append(Path("~/.config/local-genai-mcp/config.toml").expanduser())
    return paths


def _pick(cls, data: dict):
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"[{cls.__name__}] 不明な設定項目があります: {', '.join(sorted(unknown))}")
    return cls(**data)


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = next((p for p in candidate_paths() if p.is_file()), None)
    if path is None:
        searched = "\n  ".join(str(p) for p in candidate_paths())
        raise FileNotFoundError(
            "設定ファイル(config.toml)が見つかりません。config.example.toml をコピーして作成してください。\n"
            f"探した場所:\n  {searched}"
        )

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    ollama = _pick(OllamaConfig, raw.get("ollama", {}))
    forge_raw = dict(raw.get("forge", {}))
    defaults = _pick(ForgeDefaults, forge_raw.pop("defaults", {}))
    forge = _pick(ForgeConfig, {**forge_raw, "defaults": defaults})
    ollama.base_url = ollama.base_url.rstrip("/")
    forge.base_url = forge.base_url.rstrip("/")
    return Config(ollama=ollama, forge=forge, source=path)
