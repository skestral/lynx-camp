from __future__ import annotations

from backend.app.db import Store
from backend.app.presets import import_preset_pack, list_preset_packs


def test_preset_import_adds_targets_and_marks_imported(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    result = import_preset_pack(store, "pacific-northwest-national-parks", min_poll_interval_minutes=10)
    packs = list_preset_packs(store)
    imported_pack = next(pack for pack in packs if pack["id"] == "pacific-northwest-national-parks")

    assert result["imported_count"] == 29
    assert result["updated_count"] == 0
    assert imported_pack["imported_count"] == imported_pack["target_count"]
    assert {target["campground_id"] for target in store.list_targets()} >= {"232464", "232466", "10337002", "258799"}


def test_requested_national_park_packs_are_available(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    packs = {pack["id"]: pack for pack in list_preset_packs(store)}

    assert packs["olympic-national-park"]["target_count"] == 6
    assert packs["mount-rainier-national-park"]["target_count"] == 5
    assert packs["crater-lake-national-park"]["target_count"] == 1
    assert packs["north-cascades-national-park"]["target_count"] == 8
    assert packs["glacier-national-park"]["target_count"] == 9
    assert packs["yellowstone-national-park"]["target_count"] == 5
    assert packs["grand-teton-national-park"]["target_count"] == 9


def test_preset_reimport_updates_existing_targets(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    import_preset_pack(store, "california-national-parks", min_poll_interval_minutes=10)
    result = import_preset_pack(store, "california-national-parks", min_poll_interval_minutes=10)

    assert result["imported_count"] == 0
    assert result["updated_count"] == result["target_count"]
