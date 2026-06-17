from mobile_world.core.api import env
from mobile_world.runtime.utils import docker


def test_list_containers_matches_memgui_prefix_when_image_is_raw_id(monkeypatch):
    monkeypatch.setattr(
        env,
        "list_containers_by_image_or_prefix",
        lambda *_args, **_kwargs: [
            {
                "Names": "memgui_bench_env_0",
                "Image": "00085885794b",
                "Status": "Up 7 hours (healthy)",
                "Ports": (
                    "0.0.0.0:6804->6800/tcp, "
                    "0.0.0.0:7864->7860/tcp, "
                    "0.0.0.0:5560->5556/tcp"
                ),
            }
        ],
    )

    containers = env.list_containers()

    assert len(containers) == 1
    assert containers[0].name == "memgui_bench_env_0"
    assert containers[0].image == "00085885794b"
    assert containers[0].backend_port == 6804
    assert containers[0].viewer_port == 7864
    assert containers[0].adb_port == 5560


def test_remove_containers_matches_memgui_prefix_when_image_is_raw_id(monkeypatch):
    removed = []
    monkeypatch.setattr(
        env,
        "list_containers_by_image_or_prefix",
        lambda *_args, **_kwargs: [
            {"Names": "memgui_bench_env_0", "Image": "00085885794b"},
            {"Names": "unrelated_env_0", "Image": "00085885794b"},
        ],
    )
    monkeypatch.setattr(
        env,
        "remove_container",
        lambda name, force=True: removed.append(name) or True,
    )

    destroyed, failed = env.remove_containers()

    assert destroyed == ["memgui_bench_env_0"]
    assert failed == []
    assert removed == ["memgui_bench_env_0"]


def test_discover_backends_matches_memgui_prefix_when_image_is_raw_id(monkeypatch):
    monkeypatch.setattr(
        docker,
        "docker_ps",
        lambda include_all=False: [
            {
                "Names": "memgui_bench_env_0",
                "Image": "00085885794b",
                "Status": "Up 7 hours (healthy)",
            }
        ],
    )
    monkeypatch.setattr(
        docker,
        "docker_inspect",
        lambda _name: {
            "NetworkSettings": {
                "Ports": {
                    "6800/tcp": [{"HostPort": "6804"}],
                    "7860/tcp": [{"HostPort": "7864"}],
                    "5556/tcp": [{"HostPort": "5560"}],
                }
            }
        },
    )

    backend_urls, container_names = docker.discover_backends(
        image_filter="crpi.example.com/memgui/memgui-bench:26061401",
        prefix="memgui_bench_env",
    )

    assert backend_urls == ["http://localhost:6804"]
    assert container_names == ["memgui_bench_env_0"]
