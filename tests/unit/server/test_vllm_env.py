from __future__ import annotations

from pathlib import Path

import pytest

from parsehawk.server.runtime import vllm_env


def _make_fake_venv(venv_dir: Path) -> Path:
    python_bin = venv_dir / "bin" / "python"
    python_bin.parent.mkdir(parents=True, exist_ok=True)
    python_bin.write_text("", encoding="utf-8")
    (venv_dir / "lib" / "python3.12" / "site-packages").mkdir(parents=True, exist_ok=True)
    return python_bin


def test_vllm_launch_env_disables_flashinfer_sampler() -> None:
    assert vllm_env.vllm_launch_env()["VLLM_USE_FLASHINFER_SAMPLER"] == "0"


def test_vllm_launch_env_can_set_metal_memory_fraction() -> None:
    assert vllm_env.vllm_launch_env(metal_memory_fraction=0.5) == {
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
        "VLLM_METAL_MEMORY_FRACTION": "0.5",
    }


def test_ensure_vllm_venv_reuses_cached_env_and_refreshes_patch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv_dir = tmp_path / "vllm-venv"
    _make_fake_venv(venv_dir)
    (venv_dir / ".parsehawk-ready").write_text("vllm==0.23.0", encoding="utf-8")

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("a cached venv must not be rebuilt")

    monkeypatch.setattr(vllm_env.subprocess, "run", fail)

    python_bin = vllm_env.ensure_vllm_venv(venv_dir, pip_spec="vllm==0.23.0", python_version="3.12")

    assert python_bin == venv_dir / "bin" / "python"
    site_packages = venv_dir / "lib" / "python3.12" / "site-packages"
    assert (site_packages / f"{vllm_env.PATCH_MODULE_NAME}.py").exists()
    pth = (site_packages / f"{vllm_env.PATCH_MODULE_NAME}.pth").read_text(encoding="utf-8")
    assert pth.strip() == f"import {vllm_env.PATCH_MODULE_NAME}"


def test_ensure_vllm_venv_rebuilds_when_spec_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv_dir = tmp_path / "vllm-venv"
    _make_fake_venv(venv_dir)
    (venv_dir / ".parsehawk-ready").write_text("vllm==0.21.0", encoding="utf-8")

    calls: list[list[str]] = []
    monkeypatch.setattr(vllm_env.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(vllm_env.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))

    vllm_env.ensure_vllm_venv(
        venv_dir, pip_spec="vllm==0.23.0", python_version="3.12", log=lambda _msg: None
    )

    assert any(cmd[:2] == ["/usr/bin/uv", "venv"] for cmd in calls)
    assert any(cmd[:3] == ["/usr/bin/uv", "pip", "install"] for cmd in calls)
    assert (venv_dir / ".parsehawk-ready").read_text(encoding="utf-8") == "vllm==0.23.0"
