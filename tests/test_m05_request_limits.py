"""R-M05-6 proves unknown-length uploads are rejected before body consumption."""


def test_chunked_body_over_16_kib_is_rejected_without_reading_it(client):
    consumed = 0

    def chunks():
        nonlocal consumed
        for _ in range(3):
            consumed += 1
            yield b"x" * 8192

    response = client.post(
        "/api/v1/forecasts",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 411
    assert response.json()["error"]["code"] == "content_length_required"
    assert consumed == 0
