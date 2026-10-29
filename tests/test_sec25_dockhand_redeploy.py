"""SEC-25: redeploying a stack never runs `docker compose` in dockhand (its folder comes from
container labels anyone who can create a container can set); it restarts the stack's
containers in dependency order through the Docker API proxy."""

from backend.services import compose_synthesizer, docker_stacks


def test_a_dockhand_stack_is_restarted_not_composed(monkeypatch):
    monkeypatch.setattr(
        docker_stacks,
        "get_stack_details",
        lambda name: {
            "containers": [{"id": "db1", "name": "db"}, {"id": "web1", "name": "web"}],
            "location_type": "dockhand",
            "working_dir": "/srv/anything; rm -rf /",
            "compose_yaml": "services:\n  web:\n    depends_on: [db]\n  db: {}\n",
        },
    )
    restarted = []

    def docker(method, path, *a, **k):
        restarted.append((method, path))
        return 204, None

    def never(*a, **k):
        raise AssertionError("ran a command in a container")

    monkeypatch.setattr(docker_stacks, "_docker_request", docker)
    monkeypatch.setattr(compose_synthesizer, "execute_in_container", never)
    res = docker_stacks.execute_stack_action("blog", "redeploy")
    assert res["success"] and res["action"] == "redeploy"
    assert [p for _, p in restarted] == ["/containers/db1/restart?t=10", "/containers/web1/restart?t=10"]
    assert not hasattr(docker_stacks, "execute_in_container")
