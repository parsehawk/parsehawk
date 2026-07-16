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
DEFAULT_VLLM_MAX_NUM_SEQS = 1
DEFAULT_VLLM_PIP_SPEC = "vllm==0.23.0"
DEFAULT_VLLM_PYTHON_VERSION = "3.12"
DEFAULT_NUEXTRACT_KEEP_ALIVE_SECONDS = 300
DEFAULT_PDF_MAX_PAGES = 25
DEFAULT_PDF_RENDER_DPI = 170
# The vLLM Metal runtime is provisioned from two pinned artifacts: the vLLM
# source release the plugin was built against, and the vllm-metal wheel from
# the matching GitHub release tag. Bump both together — a vllm-metal release
# pins its vLLM version in the upstream install.sh at the same tag.
DEFAULT_VLLM_METAL_VERSION = "0.3.0.dev20260708043308"
DEFAULT_VLLM_METAL_VLLM_VERSION = "0.24.0"


def default_inference_engine() -> str | None:
    """Return the inference engine bundled for this platform, or None.

    Single source of truth shared by the CLI runtime default and the dependency
    markers. Both macOS Apple Silicon and
    Linux x86_64 and ARM64 use the OpenAI-compatible vLLM runtime contract;
    macOS reaches that contract through vLLM Metal on the host.
    """
    machine = platform.machine()
    if sys.platform == "darwin" and machine == "arm64":
        return "vllm"
    if sys.platform.startswith("linux") and machine in {"x86_64", "aarch64", "arm64"}:
        return "vllm"
    return None


class Settings(BaseSettings):
    """Environment-backed settings shared by the API, worker, and local runtime."""

    model_config = SettingsConfigDict(env_prefix="PARSEHAWK_", extra="ignore")

    data_dir: Path = Field(
        default=DEFAULT_DATA_DIR,
        description="Directory for the database, uploaded files, secrets, and runtime state.",
    )
    database_path: Path | None = Field(
        default=None,
        description="SQLite database path. Defaults to <data_dir>/parsehawk.db.",
    )
    log_level: str = Field(
        default="INFO",
        description="Python logging level for ParseHawk services.",
    )
    log_model_io: bool = Field(
        default=False,
        description="Log model prompts and responses. May expose sensitive document content.",
    )
    secret_key: str | None = Field(
        default=None,
        description="Encryption key override for stored provider secrets.",
        json_schema_extra={"writeOnly": True},
    )
    inference_engine: str = Field(
        default="none",
        description="Bundled inference engine. Use 'vllm' or 'none'.",
    )
    vllm_base_url: str = Field(
        default="http://127.0.0.1:8080/v1",
        description="OpenAI-compatible base URL for the local vLLM runtime.",
    )
    vllm_model: str = Field(
        default=DEFAULT_VLLM_MODEL,
        description="Model identifier served by the bundled vLLM runtime.",
    )
    vllm_max_tokens: int = Field(
        default=2048,
        ge=1,
        description="Maximum generated tokens per extraction request.",
    )
    vllm_temperature: float = Field(
        default=0.2,
        ge=0,
        description="Sampling temperature for the bundled runtime.",
    )
    vllm_timeout_seconds: int = Field(
        default=600,
        ge=1,
        description="Timeout for one model request in seconds.",
    )
    vllm_max_model_len: int = Field(
        default=DEFAULT_VLLM_MAX_MODEL_LEN,
        ge=1,
        description="Maximum vLLM context length in tokens.",
    )
    vllm_max_num_seqs: int = Field(
        default=DEFAULT_VLLM_MAX_NUM_SEQS,
        ge=1,
        description="Maximum number of sequences vLLM processes concurrently.",
    )
    vllm_gpu_memory_utilization: float = Field(
        default=DEFAULT_VLLM_GPU_MEMORY_UTILIZATION,
        gt=0,
        le=1,
        description="Fraction of GPU memory available to vLLM on NVIDIA systems.",
    )
    vllm_enable_mtp: bool = Field(
        default=False,
        description="Enable multi-token prediction when the selected vLLM model supports it.",
    )
    vllm_venv_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "parsehawk" / "vllm-venv",
        description="Managed virtual environment for the Linux vLLM runtime.",
    )
    vllm_pip_spec: str = Field(
        default=DEFAULT_VLLM_PIP_SPEC,
        description="Pinned pip requirement used to provision Linux vLLM.",
    )
    vllm_python_version: str = Field(
        default=DEFAULT_VLLM_PYTHON_VERSION,
        description="Python version used for the managed Linux vLLM environment.",
    )
    vllm_metal_home: Path = Field(
        default_factory=lambda: Path.home() / ".parsehawk" / "runtimes" / "vllm-metal",
        description="Installation directory for the macOS vLLM Metal runtime.",
    )
    vllm_metal_version: str = Field(
        default=DEFAULT_VLLM_METAL_VERSION,
        description="Pinned vLLM Metal release identifier.",
    )
    vllm_metal_vllm_version: str = Field(
        default=DEFAULT_VLLM_METAL_VLLM_VERSION,
        description="Upstream vLLM version matched by the vLLM Metal release.",
    )
    nuextract_keep_alive_seconds: int = Field(
        default=DEFAULT_NUEXTRACT_KEEP_ALIVE_SECONDS,
        ge=0,
        description="Seconds NuExtract model state remains warm between jobs.",
    )
    pdf_max_pages: int = Field(
        default=DEFAULT_PDF_MAX_PAGES,
        ge=1,
        description="Maximum number of PDF pages rendered for one extraction.",
    )
    pdf_render_dpi: int = Field(
        default=DEFAULT_PDF_RENDER_DPI,
        ge=1,
        description="DPI used when rendering PDF pages to images.",
    )
    telemetry_disabled: bool = Field(
        default=False,
        description="Disable anonymous usage analytics when true.",
    )

    @computed_field
    @property
    def resolved_database_path(self) -> Path:
        return self.database_path or self.data_dir / "parsehawk.db"

    @classmethod
    def from_env(cls) -> Settings:
        return cls()
