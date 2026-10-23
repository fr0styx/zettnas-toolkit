"""Stack pages open only compose files inside the storage folders (audit pass 2)."""

from backend import config


def _stack(tmp_path, monkeypatch, folder):
    from backend.services import docker_stacks

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.txt").write_text("dummy line\n")
    (folder / "docker-compose.yml").write_text("services: {}\n")
    stack = {
        "name": "s",
        "containers": [{"id": "c1", "name": "c1", "state": "running"}],
        "working_dir": str(folder),
        "config_files": str(folder / "notes.txt"),
        "environment_file": "",
        "origin": "compose",
        "status": "running",
    }
    monkeypatch.setattr(docker_stacks, "list_all_stacks", lambda: [stack])
    monkeypatch.setattr(docker_stacks, "fetch_container_raw_inspect", lambda cid: {})
    return docker_stacks, stack


def test_non_compose_label_path_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")])
    docker_stacks, _ = _stack(tmp_path, monkeypatch, tmp_path / "pool" / "app")
    details = docker_stacks.get_stack_details("s")
    assert "dummy line" not in details["compose_yaml"]
    assert details["config_file"].endswith("docker-compose.yml")  # the real compose file in that folder


def test_label_paths_outside_storage_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")])
    docker_stacks, stack = _stack(tmp_path, monkeypatch, tmp_path / "elsewhere")
    stack["config_files"] = str(tmp_path / "elsewhere" / "docker-compose.yml")
    details = docker_stacks.get_stack_details("s")
    assert details["location_type"] == "synthesized"
    assert details["config_file"] == "" and details["working_dir"] == ""


def test_compose_file_in_storage_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")])
    docker_stacks, stack = _stack(tmp_path, monkeypatch, tmp_path / "pool" / "app")
    stack["config_files"] = str(tmp_path / "pool" / "app" / "docker-compose.yml")
    details = docker_stacks.get_stack_details("s")
    assert details["location_type"] == "host_fs" and details["compose_yaml"] == "services: {}\n"
