import json
import subprocess

from mobile_world.core.api import env


def _completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_image_status_needs_update_when_local_image_missing(monkeypatch):
    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return _completed(returncode=1)
        if cmd[:3] == ["docker", "manifest", "inspect"]:
            return _completed(
                stdout=json.dumps({"Descriptor": {"digest": "sha256:remote"}})
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(env.subprocess, "run", fake_run)

    status = env.check_image_status("example/image:tag")

    assert not status.exists_locally
    assert status.needs_update


def test_image_status_needs_update_when_digest_cannot_be_verified(monkeypatch):
    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return _completed(stdout=json.dumps([{"RepoDigests": []}]))
        if cmd[:3] == ["docker", "manifest", "inspect"]:
            return _completed(returncode=1)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(env.subprocess, "run", fake_run)

    status = env.check_image_status("example/image:tag")

    assert status.exists_locally
    assert status.local_digest is None
    assert status.remote_digest is None
    assert status.needs_update


def test_image_status_is_ready_when_digests_match(monkeypatch):
    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return _completed(
                stdout=json.dumps(
                    [{"RepoDigests": ["example/image@sha256:matching-digest"]}]
                )
            )
        if cmd[:3] == ["docker", "manifest", "inspect"]:
            return _completed(
                stdout=json.dumps(
                    {"Descriptor": {"digest": "sha256:matching-digest"}}
                )
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(env.subprocess, "run", fake_run)

    status = env.check_image_status("example/image:tag")

    assert status.exists_locally
    assert status.local_digest == "matching-digest"
    assert status.remote_digest == "matching-digest"
    assert not status.needs_update


def test_image_status_needs_update_when_digests_differ(monkeypatch):
    def fake_run(cmd, **_kwargs):
        if cmd[:3] == ["docker", "image", "inspect"]:
            return _completed(
                stdout=json.dumps([{"RepoDigests": ["example/image@sha256:old"]}])
            )
        if cmd[:3] == ["docker", "manifest", "inspect"]:
            return _completed(stdout=json.dumps({"Descriptor": {"digest": "sha256:new"}}))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(env.subprocess, "run", fake_run)

    status = env.check_image_status("example/image:tag")

    assert status.exists_locally
    assert status.local_digest == "old"
    assert status.remote_digest == "new"
    assert status.needs_update
