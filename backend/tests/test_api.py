import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(payload):
    return client.post("/calculate", json=payload)


# ------------------------------------------------------------------ basics
def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_city_profiles_lists_pune_and_mumbai():
    r = client.get("/city-profiles")
    assert r.status_code == 200
    body = r.json()
    assert set(body["cities"]) == {"pune", "mumbai"}
    assert body["survival_presets"]["mumbai_like"]["point"] == 0.37
    assert body["survival_presets"]["chennai_like"]["point"] == 0.63
    assert set(body["growth_classes"]["classes"]) == {"fast", "moderate", "slow"}
    for city in body["cities"].values():
        assert city["rainfall"]["source"] and city["survival"]["source"]
        assert city["compensatory_planting"]["default_promised_ratio"] > 0


def test_cors_allows_vite_dev_origin():
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ------------------------------------------------------------------ /calculate happy paths
def test_calculate_with_counts():
    r = post({"city": "pune", "tree_counts": {"small": 100, "medium": 250, "large": 179}, "promised_ratio": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inputs"]["total_trees"] == 529
    assert set(body["annual_loss"]) == {"cooling", "rainwater", "air", "carbon"}
    for service, v in body["annual_loss"].items():
        assert v["low"] < v["high"], service
        assert v["sources"] and v["unit"]
    gap = body["replacement_gap"]
    assert len(gap["as_promised"]["recovered_fraction"]) == 41
    assert len(gap["realistic"]["recovered_fraction"]) == 41
    assert gap["as_promised"]["survival"] == {"low": 1.0, "high": 1.0}
    assert body["city"]["id"] == "pune"
    assert any("not legal advice" in n for n in body["notes"])


def test_calculate_with_total_and_mix_matches_counts():
    a = post({"city": "mumbai", "total_trees": 100, "size_mix": {"small": 20, "medium": 50, "large": 30}})
    b = post({"city": "mumbai", "tree_counts": {"small": 20, "medium": 50, "large": 30}})
    assert a.status_code == b.status_code == 200
    assert a.json()["annual_loss"] == b.json()["annual_loss"]
    assert a.json()["inputs"]["tree_counts"] == {"small": 20.0, "medium": 50.0, "large": 30.0}


def test_calculate_city_is_case_insensitive_and_defaults_come_from_city():
    r = post({"city": "Mumbai", "tree_counts": {"large": 10}})
    assert r.status_code == 200
    body = r.json()
    assert body["inputs"]["promised_ratio"] == 4
    assert body["replacement_gap"]["realistic"]["survival"] == {"low": 0.35, "high": 0.5}


def test_calculate_survival_preset():
    r = post({"city": "pune", "tree_counts": {"large": 10}, "survival_preset": "chennai_like"})
    assert r.status_code == 200
    assert r.json()["replacement_gap"]["realistic"]["survival"] == {"low": 0.55, "high": 0.7}


def test_calculate_survival_overrides():
    r = post({
        "city": "pune", "tree_counts": {"large": 10}, "promised_ratio": 8,
        "promised_survival": 0.8, "realistic_survival": {"low": 0.3, "high": 0.4},
        "growth_class": "slow", "horizon_years": 60,
    })
    assert r.status_code == 200, r.text
    gap = r.json()["replacement_gap"]
    assert gap["as_promised"]["survival"] == {"low": 0.8, "high": 0.8}
    assert gap["realistic"]["survival"] == {"low": 0.3, "high": 0.4}
    assert gap["horizon_years"] == 60 and len(gap["realistic"]["recovered_fraction"]) == 61
    assert r.json()["inputs"]["growth_class"] == "slow"


def test_realistic_never_beats_as_promised_through_api():
    body = post({"city": "mumbai", "tree_counts": {"medium": 40, "large": 20}, "promised_ratio": 6}).json()
    ap = body["replacement_gap"]["as_promised"]["recovered_fraction"]
    re_ = body["replacement_gap"]["realistic"]["recovered_fraction"]
    for a, r in zip(ap, re_):
        assert r["high"] <= a["high"] + 1e-9
        assert r["low"] <= a["low"] + 1e-9


def test_every_number_group_has_a_source():
    body = post({"city": "pune", "tree_counts": {"small": 5, "large": 5}}).json()
    for v in body["annual_loss"].values():
        for s in v["sources"]:
            assert s["source"] and s["verification_status"]
    for key, v in body["replacement_gap"]["sources"].items():
        assert v["source"] and v["verification_status"], key


# ------------------------------------------------------------------ /calculate errors
@pytest.mark.parametrize(
    "payload, status",
    [
        ({"city": "delhi", "tree_counts": {"large": 1}}, 404),
        ({"city": "pune"}, 422),
        ({"city": "pune", "tree_counts": {}}, 422),  # zero trees
        ({"city": "pune", "tree_counts": {"large": -1}}, 422),
        ({"city": "pune", "tree_counts": {"giant": 1}}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "total_trees": 5, "size_mix": {"large": 1}}, 422),
        ({"city": "pune", "total_trees": 5}, 422),
        ({"city": "pune", "total_trees": 5, "size_mix": {"large": 0}}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "promised_ratio": -2}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "realistic_survival": 1.5}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "realistic_survival": {"low": 0.6, "high": 0.4}}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "survival_preset": "nowhere_like"}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "survival_preset": "mumbai_like", "realistic_survival": 0.5}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "growth_class": "giant"}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "horizon_years": 0}, 422),
        ({"city": "pune", "tree_counts": {"large": 1}, "surprise": True}, 422),
    ],
)
def test_calculate_rejects_bad_input(payload, status):
    assert post(payload).status_code == status


# ------------------------------------------------------------------ data integrity
def test_services_data_entries_are_complete_and_ranges():
    from app.data import load_services_ranges

    data = load_services_ranges()
    assert len(data["services"]) == 12
    seen = set()
    for e in data["services"]:
        assert e["source"].strip() and e["note"].strip() and e["verification_status"].strip()
        assert 0 <= e["low"] < e["high"], e["id"]
        seen.add((e["service"], e["size_class"]))
    assert seen == {(s, c) for s in ("cooling", "rainwater", "air", "carbon") for c in ("small", "medium", "large")}
    # larger trees never have a lower range than smaller trees of the same service
    by = {(e["service"], e["size_class"]): e for e in data["services"]}
    for s in ("cooling", "rainwater", "air", "carbon"):
        assert by[(s, "small")]["high"] <= by[(s, "large")]["high"]
        assert by[(s, "small")]["low"] <= by[(s, "medium")]["low"] <= by[(s, "large")]["low"]


def test_city_profile_fields_present():
    from app.data import load_city_profiles

    data = load_city_profiles()
    for cid, c in data["cities"].items():
        assert c["id"] == cid
        for key in ("rainfall", "heat_context", "survival", "compensatory_planting", "species_groups"):
            assert key in c
        s = c["survival"]["realistic"]
        assert 0 < s["low"] <= s["point"] <= s["high"] <= 1
        ids = {g["id"] for g in c["species_groups"]["groups"]}
        assert c["species_groups"]["default_group"] in ids
        assert c["compensatory_planting"]["legal_source"]
