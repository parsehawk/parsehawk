from __future__ import annotations

from parsehawk.model_profiles import (
    GIB,
    RuntimePlatform,
    RuntimeProfileDefaults,
    runtime_profile_defaults,
)


def test_known_model_resolves_platform_memory_tier() -> None:
    defaults = runtime_profile_defaults(
        model="numind/NuExtract3-W4A16",
        platform=RuntimePlatform.LINUX_NVIDIA,
        memory_bytes=24 * GIB,
        fallback=RuntimeProfileDefaults(
            max_model_len=8192,
            gpu_memory_utilization=0.5,
            max_num_seqs=1,
        ),
    )

    assert defaults.max_model_len == 16384
    assert defaults.gpu_memory_utilization == 0.85
    assert defaults.max_num_seqs == 4


def test_macos_16gib_tier_uses_16k_context() -> None:
    fallback = RuntimeProfileDefaults(
        max_model_len=8192,
        gpu_memory_utilization=0.5,
        max_num_seqs=1,
    )

    for memory_bytes in (16 * GIB, 18 * GIB):
        defaults = runtime_profile_defaults(
            model="numind/NuExtract3-W4A16",
            platform=RuntimePlatform.MACOS_APPLE_SILICON,
            memory_bytes=memory_bytes,
            fallback=fallback,
        )

        assert defaults.max_model_len == 16384
        assert defaults.gpu_memory_utilization == 0.70
        assert defaults.max_num_seqs == 1


def test_macos_below_16gib_keeps_8k_context() -> None:
    defaults = runtime_profile_defaults(
        model="numind/NuExtract3-W4A16",
        platform=RuntimePlatform.MACOS_APPLE_SILICON,
        memory_bytes=8 * GIB,
        fallback=RuntimeProfileDefaults(
            max_model_len=32768,
            gpu_memory_utilization=0.5,
            max_num_seqs=4,
        ),
    )

    assert defaults.max_model_len == 8192


def test_unknown_model_uses_fallback_defaults() -> None:
    defaults = runtime_profile_defaults(
        model="custom/model",
        platform=RuntimePlatform.MACOS_APPLE_SILICON,
        memory_bytes=64 * GIB,
        fallback=RuntimeProfileDefaults(
            max_model_len=8192,
            gpu_memory_utilization=0.5,
            max_num_seqs=1,
        ),
    )

    assert defaults == RuntimeProfileDefaults(
        max_model_len=8192,
        gpu_memory_utilization=0.5,
        max_num_seqs=1,
    )
