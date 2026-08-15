from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_frontend_safe_settings(client: TestClient) -> None:
    health = client.get("/api/health")
    settings = client.get("/api/settings")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "cluster-monitor",
        "version": "0.1.0",
    }
    assert settings.status_code == 200
    assert settings.json() == {
        "refresh": {
            "overview_seconds": 11,
            "jobs_seconds": 12,
            "nodes_seconds": 31,
            "partitions_seconds": 32,
            "history_seconds": 61,
        },
        "default_cluster_id": "local-mock",
    }
    assert "ssh_host" not in settings.text


def test_cluster_list_and_details_include_unavailable_cluster(client: TestClient) -> None:
    response = client.get("/api/clusters")

    assert response.status_code == 200
    assert [cluster["id"] for cluster in response.json()] == ["local-mock", "ssh-demo"]
    assert response.json()[0]["connection_status"] == "connected"
    assert response.json()[0]["job_actions_enabled"] is True
    assert response.json()[1]["connection_status"] == "unavailable"
    assert response.json()[1]["job_actions_enabled"] is False
    assert "test configuration" in response.json()[1]["last_error"]
    assert "hpc-alias" not in response.text

    details = client.get("/api/clusters/ssh-demo")
    assert details.status_code == 200
    assert details.json()["backend"] == "ssh"
    assert details.json()["slurm_version"] is None


def test_mock_overview_and_resource_endpoints(client: TestClient) -> None:
    overview = client.get("/api/clusters/local-mock/overview")
    partitions = client.get("/api/clusters/local-mock/partitions")
    nodes = client.get("/api/clusters/local-mock/nodes")

    assert overview.status_code == 200
    assert overview.json() == {
        "cluster_id": "local-mock",
        "connection_status": "connected",
        "slurm_version": "24.05.4-mock",
        "total_nodes": 4,
        "idle_nodes": 1,
        "allocated_nodes": 2,
        "unavailable_nodes": 1,
        "running_jobs": 2,
        "pending_jobs": 2,
        "last_refresh": "2026-01-15T12:00:00Z",
        "last_error": None,
    }
    assert partitions.status_code == 200
    assert {partition["name"] for partition in partitions.json()} == {"compute", "gpu"}
    assert nodes.status_code == 200
    assert {node["state"] for node in nodes.json()} >= {"idle", "allocated", "drained"}


def test_topology_returns_one_enriched_snapshot(client: TestClient) -> None:
    response = client.get("/api/clusters/local-mock/topology")

    assert response.status_code == 200
    assert response.json()["kind"] == "tree"
    assert response.json()["partitions"][0]["node_names"]
    assert response.json()["nodes"][0]["sockets"] == 2
    assert response.json()["groups"][0]["kind"] == "switch"


def test_read_only_file_routes_browse_and_preview_without_caching(client: TestClient) -> None:
    directory = client.post(
        "/api/clusters/local-mock/files/list",
        json={"path": "/home/student", "show_hidden": False},
    )
    preview = client.post(
        "/api/clusters/local-mock/files/preview",
        json={"path": "/home/student/project/job.sh"},
    )

    assert directory.status_code == 200
    assert directory.headers["cache-control"] == "no-store"
    assert [entry["name"] for entry in directory.json()["entries"]] == ["logs", "project"]
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert preview.json()["status"] == "available"
    assert preview.json()["content"].startswith("#!/bin/bash")


def test_file_browser_has_no_mutation_routes(client: TestClient) -> None:
    path = "/api/clusters/local-mock/files/preview"

    assert client.put(path, json={"path": "/tmp/a"}).status_code == 405
    assert client.patch(path, json={"path": "/tmp/a"}).status_code == 405
    assert client.delete(path).status_code == 405


def test_file_browser_returns_stable_invalid_path_errors(client: TestClient) -> None:
    relative = client.post(
        "/api/clusters/local-mock/files/list",
        json={"path": "relative/path"},
    )
    nul = client.post(
        "/api/clusters/local-mock/files/preview",
        json={"path": "/home/student/bad\u0000path"},
    )

    assert relative.status_code == 422
    assert relative.json()["error"]["code"] == "remote_path_invalid"
    assert nul.status_code == 422
    assert nul.json()["error"]["code"] == "remote_path_invalid"


def test_nodes_can_be_filtered(client: TestClient) -> None:
    by_state = client.get("/api/clusters/local-mock/nodes", params={"state": "drained"})
    by_partition = client.get(
        "/api/clusters/local-mock/nodes",
        params={"partition": "gpu"},
    )

    assert [node["name"] for node in by_state.json()] == ["cpu003"]
    assert [node["name"] for node in by_partition.json()] == ["gpu001"]


def test_jobs_default_user_filters_and_limits(client: TestClient) -> None:
    all_jobs = client.get("/api/clusters/local-mock/jobs")
    running = client.get(
        "/api/clusters/local-mock/jobs",
        params={"state": "running", "partition": "gpu"},
    )
    limited = client.get("/api/clusters/local-mock/jobs", params={"limit": 1})
    other_user = client.get(
        "/api/clusters/local-mock/jobs",
        params={"user": "another-user"},
    )

    assert all_jobs.status_code == 200
    assert len(all_jobs.json()) == 4
    assert all(job["user"] == "student" for job in all_jobs.json())
    assert [job["job_id"] for job in running.json()] == ["12002"]
    assert len(limited.json()) == 1
    assert other_user.json() == []


def test_job_details_and_history(client: TestClient) -> None:
    details = client.get("/api/clusters/local-mock/jobs/11998")
    history = client.get(
        "/api/clusters/local-mock/history",
        params={"state": "failed"},
    )

    assert details.status_code == 200
    assert details.json()["exit_code"] == "0:0"
    assert details.json()["accounting"]["max_rss_mb"] > 0
    assert details.json()["working_directory"].startswith("/home/student/")
    assert [job["job_id"] for job in history.json()] == ["11997"]


def test_mock_job_logs_are_streamed_as_path_free_sse(client: TestClient) -> None:
    response = client.get("/api/clusters/local-mock/jobs/12001/logs/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: metadata" in response.text
    assert '"sources":["stdout","stderr"]' in response.text
    assert "event: chunk" in response.text
    assert "mock standard output" in response.text
    assert "/home/student" not in response.text


def test_mock_merged_job_log_is_deduplicated(client: TestClient) -> None:
    response = client.get("/api/clusters/local-mock/jobs/12002/logs/stream")

    assert response.status_code == 200
    assert '"sources":["combined"]' in response.text
    assert response.text.count("event: chunk") == 1


def test_log_route_rejects_unsupported_identifiers_and_unavailable_cluster(
    client: TestClient,
) -> None:
    step = client.get("/api/clusters/local-mock/jobs/12001.batch/logs/stream")
    heterogeneous = client.get("/api/clusters/local-mock/jobs/12001+1/logs/stream")
    unavailable = client.get("/api/clusters/ssh-demo/jobs/12001/logs/stream")

    assert step.status_code == 422
    assert heterogeneous.status_code == 422
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "cluster_unavailable"


def test_job_submission_requires_confirmation_and_returns_receipt(
    client: TestClient,
) -> None:
    payload = {
        "job_name": "smoke-test",
        "script": "#!/usr/bin/env bash\nhostname\n",
        "partition": "compute",
        "nodes": 1,
        "cpus_per_task": 2,
        "memory_mb": 2048,
        "time_limit_minutes": 5,
        "gpus_per_node": 0,
    }

    unconfirmed = client.post("/api/clusters/local-mock/jobs", json=payload)
    submitted = client.post(
        "/api/clusters/local-mock/jobs",
        json=payload,
        headers={"X-Cluster-Monitor-Action": "confirmed"},
    )
    jobs = client.get("/api/clusters/local-mock/jobs")

    assert unconfirmed.status_code == 422
    assert submitted.status_code == 201
    assert submitted.json() == {
        "cluster_id": "local-mock",
        "job_id": "13000",
        "submitted_at": "2026-01-15T12:00:00Z",
        "scheduler_cluster": None,
        "status": "submitted",
    }
    assert [job["job_id"] for job in jobs.json()].count("13000") == 1


def test_job_submission_validates_script_and_resources(client: TestClient) -> None:
    response = client.post(
        "/api/clusters/local-mock/jobs",
        json={
            "job_name": "unsafe name",
            "script": "hostname",
            "nodes": 0,
            "cpus_per_task": 1,
            "time_limit_minutes": 5,
            "gpus_per_node": 0,
        },
        headers={"X-Cluster-Monitor-Action": "confirmed"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_job_cancellation_requires_confirmation_and_updates_mock_queue(
    client: TestClient,
) -> None:
    unconfirmed = client.delete("/api/clusters/local-mock/jobs/12001")
    cancelled = client.delete(
        "/api/clusters/local-mock/jobs/12001",
        headers={"X-Cluster-Monitor-Action": "confirmed"},
    )
    jobs = client.get("/api/clusters/local-mock/jobs")
    details = client.get("/api/clusters/local-mock/jobs/12001")

    assert unconfirmed.status_code == 422
    assert cancelled.status_code == 200
    assert cancelled.json() == {
        "cluster_id": "local-mock",
        "job_id": "12001",
        "requested_at": "2026-01-15T12:00:00Z",
        "status": "cancellation_requested",
    }
    assert "12001" not in {job["job_id"] for job in jobs.json()}
    assert details.json()["state"] == "cancelled"


def test_terminal_job_cancellation_returns_conflict(client: TestClient) -> None:
    response = client.delete(
        "/api/clusters/local-mock/jobs/11998",
        headers={"X-Cluster-Monitor-Action": "confirmed"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_action_rejected"
    assert response.json()["error"]["details"]["job_id"] == "11998"


def test_array_job_cancellation_is_rejected_at_the_api_boundary(
    client: TestClient,
) -> None:
    response = client.delete(
        "/api/clusters/local-mock/jobs/12001_7",
        headers={"X-Cluster-Monitor-Action": "confirmed"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_missing_resources_use_consistent_errors(client: TestClient) -> None:
    cluster = client.get("/api/clusters/not-configured")
    job = client.get("/api/clusters/local-mock/jobs/999999")

    assert cluster.status_code == 404
    assert cluster.json() == {
        "error": {
            "code": "cluster_not_found",
            "message": "Cluster 'not-configured' is not configured.",
            "cluster_id": "not-configured",
        }
    }
    assert job.status_code == 404
    assert job.json()["error"]["code"] == "job_not_found"
    assert job.json()["error"]["details"] == {"job_id": "999999"}


def test_unavailable_ssh_cluster_returns_structured_503(client: TestClient) -> None:
    for suffix in ("overview", "partitions", "nodes", "topology", "jobs", "history"):
        response = client.get(f"/api/clusters/ssh-demo/{suffix}")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "cluster_unavailable"
        assert response.json()["error"]["cluster_id"] == "ssh-demo"
        assert "test configuration" in response.json()["error"]["message"]

    job = client.get("/api/clusters/ssh-demo/jobs/123")
    assert job.status_code == 503
    assert job.json()["error"]["code"] == "cluster_unavailable"


def test_query_validation_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/clusters/local-mock/jobs", params={"limit": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"][0]["location"] == ["query", "limit"]


def test_framework_errors_use_error_envelope(client: TestClient) -> None:
    missing_route = client.get("/api/not-a-route")
    wrong_method = client.post("/api/health")

    assert missing_route.status_code == 404
    assert missing_route.json()["error"] == {
        "code": "http_error",
        "message": "Not Found",
    }
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"] == {
        "code": "http_error",
        "message": "Method Not Allowed",
    }
