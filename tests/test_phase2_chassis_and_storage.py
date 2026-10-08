def test_disk_locate_invalid_device(client, auth_headers):
    # Attempting to locate an invalid device name should fail with 400
    res = client.post("/api/disk/locate", json={"dev": "../../etc/shadow", "duration": 5}, headers=auth_headers)
    assert res.status_code == 400
    assert "Invalid device parameter" in res.json()["detail"]


def test_disk_locate_nonexistent_valid_format(client, auth_headers):
    # Valid format device name that does not exist on disk
    res = client.post("/api/disk/locate", json={"dev": "sdz", "duration": 3}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "does not exist" in data["error"]
