import pytest

from toyoko_watch.web import WebService


class FakeService:
    def __init__(self):
        self.deleted = []

    def snapshot(self):
        return {"status": {"tasks": 2}, "tasks": [], "targets": []}

    def search_hotels(self, query, limit=100):
        return [{"hotel_id": "00075", "name": query, "limit": limit}]

    def delete_task(self, task_id):
        self.deleted.append(task_id)

    async def check_all(self, task_id=None):
        return {"task_id": task_id, "new_events": 0}


def test_web_service_returns_snapshot_and_local_hotel_search():
    web = WebService(FakeService())

    assert web.snapshot()["status"]["tasks"] == 2
    assert web.hotels("横浜", 25)[0] == {
        "hotel_id": "00075",
        "name": "横浜",
        "limit": 25,
    }


@pytest.mark.asyncio
async def test_web_service_deletes_and_checks_one_task():
    service = FakeService()
    web = WebService(service)

    assert web.delete_task("watch-1") == {"deleted": True}
    assert service.deleted == ["watch-1"]
    assert await web.check_task("watch-1") == {"task_id": "watch-1", "new_events": 0}
