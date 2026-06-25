from __future__ import annotations

import platform
import sys
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATA_DIR = Path("data")
DEFAULT_MODEL = "numind/NuExtract3-W4A16"
DEFAULT_VLLM_MODEL = DEFAULT_MODEL
DEFAULT_VLLM_MAX_MODEL_LEN = 8192
DEFAULT_VLLM_GPU_MEMORY_UTILIZATION = 0.5
DEFAULT_VLLM_PIP_SPEC = "vllm==0.23.0"
DEFAULT_VLLM_PYTHON_VERSION = "3.12"
DEFAULT_NUEXTRACT_KEEP_ALIVE_SECONDS = 300
DEFAULT_PDF_MAX_PAGES = 25
DEFAULT_PDF_RENDER_DPI = 170
DEFAULT_VLLM_METAL_INSTALL_URL = (
    "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/install.sh"
)


def default_inference_engine() -> str | None:
    """Return the inference engine bundled for this platform, or None.

    Single source of truth shared by the CLI runtime default and the dependency
    markers. Both macOS Apple Silicon and
    Linux x86_64 use the OpenAI-compatible vLLM runtime contract; macOS reaches
    that contract through vLLM Metal on the host.
    """
    machine = platform.machine()
    if sys.platform == "darwin" and machine == "arm64":
        return "vllm"
    if sys.platform.startswith("linux") and machine == "x86_64":
        return "vllm"
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PARSEHAWK_", extra="ignore")

    data_dir: Path = DEFAULT_DATA_DIR
    database_path: Path | None = None
    log_level: str = "INFO"
    log_model_io: bool = False
    inference_engine: str = "none"
    vllm_base_url: str = "http://127.0.0.1:8080/v1"
    vllm_model: str = DEFAULT_VLLM_MODEL
    vllm_max_tokens: int = Field(default=2048, ge=1)
    vllm_temperature: float = Field(default=0.2, ge=0)
    vllm_timeout_seconds: int = Field(default=600, ge=1)
    vllm_max_model_len: int = Field(default=DEFAULT_VLLM_MAX_MODEL_LEN, ge=1)
    vllm_gpu_memory_utilization: float = Field(
        default=DEFAULT_VLLM_GPU_MEMORY_UTILIZATION,
        gt=0,
        le=1,
    )
    vllm_enable_mtp: bool = False
    vllm_venv_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "parsehawk" / "vllm-venv"
    )
    vllm_pip_spec: str = DEFAULT_VLLM_PIP_SPEC
    vllm_python_version: str = DEFAULT_VLLM_PYTHON_VERSION
    vllm_metal_home: Path = Field(
        default_factory=lambda: Path.home() / ".parsehawk" / "runtimes" / "vllm-metal"
    )
    vllm_metal_install_url: str = DEFAULT_VLLM_METAL_INSTALL_URL
    nuextract_keep_alive_seconds: int = Field(default=DEFAULT_NUEXTRACT_KEEP_ALIVE_SECONDS, ge=0)
    pdf_max_pages: int = Field(default=DEFAULT_PDF_MAX_PAGES, ge=1)
    pdf_render_dpi: int = Field(default=DEFAULT_PDF_RENDER_DPI, ge=1)
    telemetry_disabled: bool = False

    @computed_field
    @property
    def resolved_database_path(self) -> Path:
        return self.database_path or self.data_dir / "parsehawk.db"

    @classmethod
    def from_env(cls) -> Settings:
        return cls()
