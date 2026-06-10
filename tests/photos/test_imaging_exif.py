def test_make_json_safe_strips_null_bytes() -> None:
    """Los tags EXIF binarios de cámara (ComponentsConfiguration de Canon) traen
    bytes nulos; Postgres jsonb no acepta \\u0000 → el save() de process_photo
    explotaba y la foto quedaba clavada en "procesando" (incidente 2026-06-09)."""
    import json

    from apps.photos.imaging import _make_json_safe

    poisoned = {
        "ComponentsConfiguration": b"\x01\x02\x03\x00",
        "nested": {"inner": "a\x00b", "lista": [b"x\x00", "y\x00"]},
        "normal": "ok",
        "numero": 3200,
    }
    safe = _make_json_safe(poisoned)
    dumped = json.dumps(safe)
    assert "\\u0000" not in dumped
    assert safe["ComponentsConfiguration"] == "\x01\x02\x03"
    assert safe["nested"]["inner"] == "ab"
    assert safe["nested"]["lista"] == ["x", "y"]
    assert safe["normal"] == "ok" and safe["numero"] == 3200
