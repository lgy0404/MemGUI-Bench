from pathlib import Path

from mobile_world.core.api import env


def test_build_container_config_inherits_host_proxy_env(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://proxy.example.com:8080")
    monkeypatch.setenv("https_proxy", "http://proxy.example.com:8080")
    monkeypatch.setenv(
        "no_proxy",
        "localhost,127.0.0.1,.corp.example.com,0,1,2,3,4,5,6,7,8,9",
    )

    config = env.build_container_config(name_prefix="memgui_proxy_test", index=0)

    assert config.http_proxy == "http://proxy.example.com:8080"
    assert config.https_proxy == "http://proxy.example.com:8080"
    assert ".corp.example.com" in config.no_proxy


def test_launch_container_forwards_proxy_envs(monkeypatch, tmp_path):
    captured: dict[str, list[str]] = {}

    def fake_run_command(cmd):
        captured["cmd"] = cmd
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(env, "run_command", fake_run_command)
    monkeypatch.setattr(env, "wait_for_container_ready", lambda *args, **kwargs: True)

    config = env.build_container_config(
        name_prefix="memgui_proxy_test",
        index=0,
        backend_port=16850,
        viewer_port=17850,
        adb_port=15550,
        env_file_path=Path(tmp_path / ".env"),
        http_proxy="http://proxy.example.com:8080",
        https_proxy="http://proxy.example.com:8080",
        no_proxy="localhost,127.0.0.1,.corp.example.com",
    )

    result = env.launch_container(config)

    assert result.success
    command = " ".join(captured["cmd"])
    assert "-e http_proxy=http://proxy.example.com:8080" in command
    assert "-e HTTP_PROXY=http://proxy.example.com:8080" in command
    assert "-e https_proxy=http://proxy.example.com:8080" in command
    assert "-e HTTPS_PROXY=http://proxy.example.com:8080" in command
    assert "-e no_proxy=localhost,127.0.0.1,.corp.example.com" in command
    assert "-e NO_PROXY=localhost,127.0.0.1,.corp.example.com" in command
