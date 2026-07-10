from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from parsehawk.config import DEFAULT_VLLM_MODEL


class RuntimePlatform(StrEnum):
    MACOS_APPLE_SILICON = "macos-apple-silicon"
    LINUX_NVIDIA = "linux-nvidia"


@dataclass(frozen=True)
class RuntimeTier:
    min_memory_bytes: int
    max_model_len: int
    gpu_memory_utilization: float
    max_num_seqs: int


@dataclass(frozen=True)
class RuntimeProfileDefaults:
    max_model_len: int
    gpu_memory_utilization: float
    max_num_seqs: int


@dataclass(frozen=True)
class ModelRuntimeProfile:
    model: str
    tiers_by_platform: dict[RuntimePlatform, tuple[RuntimeTier, ...]]

    def defaults_for(
        self,
        *,
        platform: RuntimePlatform,
        memory_bytes: int | None,
        fallback: RuntimeProfileDefaults,
    ) -> RuntimeProfileDefaults:
        tiers = self.tiers_by_platform.get(platform)
        if not tiers:
            return fallback

        if memory_bytes is None:
            tier = tiers[0]
        else:
            tier = max(
                (tier for tier in tiers if memory_bytes >= tier.min_memory_bytes),
                key=lambda tier: tier.min_memory_bytes,
                default=tiers[0],
            )

        return RuntimeProfileDefaults(
            max_model_len=tier.max_model_len,
            gpu_memory_utilization=tier.gpu_memory_utilization,
            max_num_seqs=tier.max_num_seqs,
        )


GIB = 1024**3


DEFAULT_MODEL_RUNTIME_PROFILE = ModelRuntimeProfile(
    model=DEFAULT_VLLM_MODEL,
    tiers_by_platform={
        RuntimePlatform.MACOS_APPLE_SILICON: (
            RuntimeTier(
                min_memory_bytes=0,
                max_model_len=8192,
                gpu_memory_utilization=0.70,
                max_num_seqs=1,
            ),
            RuntimeTier(
                min_memory_bytes=16 * GIB,
                max_model_len=16384,
                gpu_memory_utilization=0.70,
                max_num_seqs=1,
            ),
            RuntimeTier(
                min_memory_bytes=32 * GIB,
                max_model_len=32768,
                gpu_memory_utilization=0.50,
                max_num_seqs=4,
            ),
        ),
        RuntimePlatform.LINUX_NVIDIA: (
            RuntimeTier(
                min_memory_bytes=0,
                max_model_len=8192,
                gpu_memory_utilization=0.90,
                max_num_seqs=1,
            ),
            RuntimeTier(
                min_memory_bytes=16 * GIB,
                max_model_len=16384,
                gpu_memory_utilization=0.85,
                max_num_seqs=4,
            ),
            RuntimeTier(
                min_memory_bytes=32 * GIB,
                max_model_len=32768,
                gpu_memory_utilization=0.75,
                max_num_seqs=8,
            ),
        ),
    },
)

MODEL_RUNTIME_PROFILES = {
    DEFAULT_MODEL_RUNTIME_PROFILE.model.lower(): DEFAULT_MODEL_RUNTIME_PROFILE
}


def runtime_profile_defaults(
    *,
    model: str,
    platform: RuntimePlatform,
    memory_bytes: int | None,
    fallback: RuntimeProfileDefaults,
) -> RuntimeProfileDefaults:
    profile = MODEL_RUNTIME_PROFILES.get(model.lower())
    if profile is None:
        return fallback
    return profile.defaults_for(platform=platform, memory_bytes=memory_bytes, fallback=fallback)
