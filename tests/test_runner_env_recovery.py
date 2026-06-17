from types import SimpleNamespace

import pytest

from mobile_world.core import runner
from mobile_world.core.api import env as env_api
from mobile_world.runtime.utils import docker as docker_utils


def test_initialize_env_pool_skips_unhealthy_backend(monkeypatch):
    def fake_init_env_once(env_url, *_args, **_kwargs):
        if env_url == "http://bad-env":
            raise RuntimeError(
                'Device is not healthy: {"detail":"Device is not healthy; '
                'emulator recovery in_progress"}'
            )
        return SimpleNamespace(base_url=env_url)

    monkeypatch.setattr(runner, "_init_env_once", fake_init_env_once)
    monkeypatch.setattr(runner, "_recover_backend_env", lambda *args, **kwargs: None)

    envs, container_names = runner._initialize_env_pool(
        aw_urls=["http://bad-env", "http://good-env"],
        container_names=["bad-container", "good-container"],
        device="emulator-5554",
        step_wait_time=1.0,
        suite_family="memgui_bench",
        enable_mcp=False,
        max_concurrency=2,
    )

    assert [env.base_url for env in envs] == ["http://good-env"]
    assert container_names == ["good-container"]


def test_initialize_env_pool_raises_when_all_backends_are_unhealthy(monkeypatch):
    def fake_init_env_once(env_url, *_args, **_kwargs):
        raise RuntimeError(f"Device is not healthy: {env_url}")

    monkeypatch.setattr(runner, "_init_env_once", fake_init_env_once)
    monkeypatch.setattr(runner, "_recover_backend_env", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="No healthy backend environments available"):
        runner._initialize_env_pool(
            aw_urls=["http://bad-env-0", "http://bad-env-1"],
            container_names=["bad-container-0", "bad-container-1"],
            device="emulator-5554",
            step_wait_time=1.0,
            suite_family="memgui_bench",
            enable_mcp=False,
            max_concurrency=2,
        )


def test_initialize_env_pool_recovers_by_restarting_emulator(monkeypatch):
    calls = {"init": 0, "restart": 0, "rebuild": 0}

    def fake_init_env_once(env_url, *_args, **_kwargs):
        calls["init"] += 1
        if calls["init"] == 1:
            raise RuntimeError("Device is not healthy: emulator recovery in_progress")
        return SimpleNamespace(base_url=env_url)

    def fake_restart(container_name):
        calls["restart"] += 1
        assert container_name == "bad-container"
        return True

    monkeypatch.setattr(runner, "_init_env_once", fake_init_env_once)
    monkeypatch.setattr(runner, "_restart_emulator_in_container", fake_restart)
    monkeypatch.setattr(
        runner,
        "_rebuild_backend_container",
        lambda *args, **kwargs: calls.__setitem__("rebuild", calls["rebuild"] + 1) or True,
    )

    envs, container_names = runner._initialize_env_pool(
        aw_urls=["http://bad-env"],
        container_names=["bad-container"],
        device="emulator-5554",
        step_wait_time=1.0,
        suite_family="memgui_bench",
        enable_mcp=False,
        max_concurrency=1,
    )

    assert [env.base_url for env in envs] == ["http://bad-env"]
    assert container_names == ["bad-container"]
    assert calls == {"init": 2, "restart": 1, "rebuild": 0}


def test_initialize_env_pool_rebuilds_container_after_restart_failures(monkeypatch):
    state = {"rebuilt": False, "restart": 0, "rebuild": 0}

    def fake_init_env_once(env_url, *_args, **_kwargs):
        if not state["rebuilt"]:
            raise RuntimeError("Device is not healthy: emulator recovery in_progress")
        return SimpleNamespace(base_url=env_url)

    def fake_restart(_container_name):
        state["restart"] += 1
        return False

    def fake_rebuild(container_name, env_image):
        state["rebuild"] += 1
        assert container_name == "bad-container"
        assert env_image == "runtime-image:latest"
        state["rebuilt"] = True
        return True

    monkeypatch.setattr(runner, "_init_env_once", fake_init_env_once)
    monkeypatch.setattr(runner, "_restart_emulator_in_container", fake_restart)
    monkeypatch.setattr(runner, "_rebuild_backend_container", fake_rebuild)
    monkeypatch.setattr(runner, "BACKEND_EMULATOR_RESTART_ATTEMPTS", 2)

    envs, container_names = runner._initialize_env_pool(
        aw_urls=["http://bad-env"],
        container_names=["bad-container"],
        device="emulator-5554",
        step_wait_time=1.0,
        suite_family="memgui_bench",
        enable_mcp=False,
        max_concurrency=1,
        env_image="runtime-image:latest",
    )

    assert [env.base_url for env in envs] == ["http://bad-env"]
    assert container_names == ["bad-container"]
    assert state == {"rebuilt": True, "restart": 2, "rebuild": 1}


def test_rebuild_backend_container_preserves_ports_mount_and_proxy(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=test\n")
    captured = {}

    monkeypatch.setattr(
        docker_utils,
        "docker_inspect",
        lambda _name: {
            "Config": {
                "Image": "old-image",
                "Entrypoint": ["/usr/local/bin/memgui-runtime-entrypoint.sh"],
                "Env": [
                    "ENABLE_VIEWER=true",
                    "EMULATOR_TIMEOUT=321",
                    "http_proxy=http://proxy.example.com:8080",
                    "https_proxy=http://proxy.example.com:8080",
                    "no_proxy=localhost,127.0.0.1",
                ],
            },
            "NetworkSettings": {
                "Ports": {
                    "6800/tcp": [{"HostPort": "6805"}],
                    "7860/tcp": [{"HostPort": "7865"}],
                    "5556/tcp": [{"HostPort": "5565"}],
                }
            },
            "Mounts": [{"Destination": "/app/service/.env", "Source": str(env_file)}],
        },
    )
    monkeypatch.setattr(env_api, "remove_container", lambda name, force=True: True)

    def fake_launch_container(config, wait_ready=True, ready_timeout=0):
        captured["config"] = config
        captured["wait_ready"] = wait_ready
        captured["ready_timeout"] = ready_timeout
        return SimpleNamespace(success=True, ready=True, error_message=None)

    monkeypatch.setattr(env_api, "launch_container", fake_launch_container)

    assert runner._rebuild_backend_container("memgui_bench_env_1", "runtime-image:latest")

    config = captured["config"]
    assert config.name == "memgui_bench_env_1"
    assert config.image == "runtime-image:latest"
    assert config.backend_port == 6805
    assert config.viewer_port == 7865
    assert config.adb_port == 5565
    assert config.enable_viewer
    assert config.emulator_timeout == 321
    assert config.env_file_path == env_file
    assert config.http_proxy == "http://proxy.example.com:8080"
    assert config.no_proxy == "localhost,127.0.0.1"
    assert captured["wait_ready"]
    assert captured["ready_timeout"] == runner.BACKEND_REBUILD_TIMEOUT_SECONDS
