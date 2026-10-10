import math

import pytest

from app import engine
from app.engine import Range

YEARS_FAST = {"small": 2, "medium": 8, "large": 20}
YEARS_RANGE = {"small": [2, 4], "medium": [8, 15], "large": [20, 35]}


# ---------------------------------------------------------------- helpers
def test_make_range_rejects_inverted():
    with pytest.raises(ValueError):
        engine.make_range(5, 1)


def test_as_range_accepts_many_forms():
    assert engine.as_range((1, 2)) == Range(1, 2)
    assert engine.as_range([1, 2]) == Range(1, 2)
    assert engine.as_range({"low": 1, "high": 2}) == Range(1, 2)
    assert engine.as_range(0.5) == Range(0.5, 0.5)
    with pytest.raises(TypeError):
        engine.as_range("x")


def test_round_range_widens_outwards():
    r = engine.round_range(Range(1234, 5678), sig=2)
    assert r == Range(1200, 5700)
    assert r.low <= 1234 and r.high >= 5678


def test_round_range_handles_small_and_exact_values():
    assert engine.round_range(Range(0.0123, 0.0456), sig=2) == Range(0.012, 0.046)
    # exact value must not be pushed up a step by float noise
    assert engine.round_range(Range(300, 3000), sig=2) == Range(300, 3000)
    assert engine.round_range(Range(0, 0), sig=2) == Range(0, 0)


def test_round_range_has_no_float_noise():
    r = engine.round_range(Range(91999.99999999999, 1999999.9999999998), sig=2)
    assert r == Range(92000.0, 2000000.0)
    assert engine.round_range(Range(0.1 + 0.2, 0.1 + 0.2), sig=2) == Range(0.3, 0.3)


def test_validate_counts_defaults_and_errors():
    assert engine.validate_counts({"large": 3}) == {"small": 0.0, "medium": 0.0, "large": 3.0}
    with pytest.raises(ValueError):
        engine.validate_counts({})
    with pytest.raises(ValueError):
        engine.validate_counts({"small": -1, "large": 2})
    with pytest.raises(ValueError):
        engine.validate_counts({"huge": 2})


def test_counts_from_mix_sums_to_total():
    counts = engine.counts_from_mix(529, {"small": 30, "medium": 50, "large": 20})
    assert sum(counts.values()) == 529
    assert counts["medium"] > counts["large"] > 0
    assert engine.counts_from_mix(10, {"large": 1}) == {"small": 0, "medium": 0, "large": 10}
    with pytest.raises(ValueError):
        engine.counts_from_mix(0, {"large": 1})
    with pytest.raises(ValueError):
        engine.counts_from_mix(10, {"large": 0})


# ---------------------------------------------------------------- service table / loss
def test_build_service_table_requires_all_sizes(toy_entries):
    table = engine.build_service_table(toy_entries)
    assert set(table) == {"cooling", "carbon"}
    assert table["cooling"]["medium"]["range"] == Range(40, 80)
    with pytest.raises(ValueError):
        engine.build_service_table([e for e in toy_entries if e["id"] != "carbon_large"])


def test_annual_loss_sums_by_class(toy_entries):
    table = engine.build_service_table(toy_entries)
    loss = engine.annual_loss({"small": 10, "medium": 5, "large": 2}, table)
    assert loss["cooling"] == Range(10 * 10 + 5 * 40 + 2 * 100, 10 * 20 + 5 * 80 + 2 * 200)


def test_annual_loss_always_a_proper_range(toy_entries):
    table = engine.build_service_table(toy_entries)
    loss = engine.annual_loss({"large": 1}, table)
    for r in loss.values():
        assert r.low < r.high


def test_annual_loss_multipliers(toy_entries):
    table = engine.build_service_table(toy_entries)
    base = engine.annual_loss({"large": 10}, table)
    scaled = engine.annual_loss({"large": 10}, table, multipliers={"large": 0.5})
    assert scaled["carbon"].low == pytest.approx(base["carbon"].low * 0.5)
    assert scaled["carbon"].high == pytest.approx(base["carbon"].high * 0.5)
    with pytest.raises(ValueError):
        engine.annual_loss({"large": 1}, table, multipliers={"large": -1})
    with pytest.raises(ValueError):
        engine.annual_loss({"large": 1}, table, multipliers={"giant": 1})


def test_size_class_weights(toy_entries):
    table = engine.build_service_table(toy_entries)
    w = engine.size_class_weights(table)
    assert w["large"] == pytest.approx(1.0)
    assert w["small"] == pytest.approx(15 / 150)
    assert w["medium"] == pytest.approx(60 / 150)
    assert w["small"] < w["medium"] < w["large"]


def test_weights_on_real_data_are_ordered(services_data):
    table = engine.build_service_table(services_data["services"])
    w = engine.size_class_weights(table)
    assert 0 < w["small"] < w["medium"] < w["large"] == pytest.approx(1.0)


# ---------------------------------------------------------------- survival & growth
def test_survival_fraction_ramps_then_flat():
    assert engine.survival_fraction(0, 0.4) == 1.0
    assert engine.survival_fraction(7, 0.4) == pytest.approx(0.4)
    assert engine.survival_fraction(3.5, 0.4) == pytest.approx(0.7)
    assert engine.survival_fraction(30, 0.4) == pytest.approx(0.4)
    assert engine.survival_fraction(5, 1.0) == 1.0
    with pytest.raises(ValueError):
        engine.survival_fraction(1, 1.5)
    with pytest.raises(ValueError):
        engine.survival_fraction(-1, 0.5)


def test_growth_weight_interpolates():
    w = {"small": 0.1, "medium": 0.4, "large": 1.0}
    assert engine.growth_weight(0, YEARS_FAST, w) == 0.0
    assert engine.growth_weight(1, YEARS_FAST, w) == pytest.approx(0.05)
    assert engine.growth_weight(2, YEARS_FAST, w) == pytest.approx(0.1)
    assert engine.growth_weight(5, YEARS_FAST, w) == pytest.approx(0.25)
    assert engine.growth_weight(8, YEARS_FAST, w) == pytest.approx(0.4)
    assert engine.growth_weight(20, YEARS_FAST, w) == pytest.approx(1.0)
    assert engine.growth_weight(100, YEARS_FAST, w) == pytest.approx(1.0)


def test_growth_weight_monotonic():
    w = {"small": 0.1, "medium": 0.4, "large": 1.0}
    vals = [engine.growth_weight(a, YEARS_FAST, w) for a in range(0, 45)]
    assert vals == sorted(vals)


def test_growth_weight_rejects_bad_input():
    w = {"small": 0.1, "medium": 0.4, "large": 1.0}
    with pytest.raises(ValueError):
        engine.growth_weight(-1, YEARS_FAST, w)
    with pytest.raises(ValueError):
        engine.growth_weight(1, {"small": 5, "medium": 3, "large": 20}, w)


# ---------------------------------------------------------------- replacement curve
W = {"small": 0.1, "medium": 0.4, "large": 1.0}


def test_recovery_curve_starts_at_zero_and_is_bounded_by_ratio():
    curve = engine.recovery_curve({"large": 10}, W, 5, 1.0, YEARS_FAST, horizon=40)
    assert len(curve) == 41
    assert curve[0] == 0.0
    # 5 large-equivalent trees per felled large tree, so it ends at 5x baseline
    assert curve[-1] == pytest.approx(5.0)


def test_lower_survival_never_helps():
    hi = engine.recovery_curve({"large": 10}, W, 3, 1.0, YEARS_FAST)
    lo = engine.recovery_curve({"large": 10}, W, 3, 0.37, YEARS_FAST)
    assert all(l <= h + 1e-12 for l, h in zip(lo, hi))
    assert lo[-1] == pytest.approx(3 * 0.37)


def test_recovery_year_basic():
    assert engine.recovery_year([0, 0.5, 1.0, 1.2]) == 2
    assert engine.recovery_year([0, 0.5, 0.9]) is None
    # a dip after first touching 1.0 does not count as recovered
    assert engine.recovery_year([0, 1.0, 0.8, 1.1, 1.2]) == 3


def test_never_recovers_when_ratio_times_survival_below_one():
    curve = engine.recovery_curve({"large": 10}, W, 2, 0.37, YEARS_FAST)
    assert engine.recovery_year(curve) is None


def test_zero_ratio_means_no_replacement():
    curve = engine.recovery_curve({"large": 10}, W, 0, 1.0, YEARS_FAST)
    assert max(curve) == 0.0
    with pytest.raises(ValueError):
        engine.recovery_curve({"large": 10}, W, -1, 1.0, YEARS_FAST)


def test_unrecovered_service_years():
    assert engine.unrecovered_service_years([0, 0.5, 1.0, 2.0]) == pytest.approx(1.5)
    assert engine.unrecovered_service_years([1.0, 1.0]) == 0.0


def test_scenario_gap_orders_corners():
    sc = engine.scenario_gap({"large": 10}, W, 10, Range(0.37, 0.5), YEARS_RANGE, horizon=40)
    for p in sc["recovered_fraction"]:
        assert p["low"] <= p["high"] + 1e-12
    best, worst = sc["recovery_year"]["best_case"], sc["recovery_year"]["worst_case"]
    assert best is not None
    assert worst is None or worst >= best
    u = sc["unrecovered_service_years"]
    assert u.low <= u.high


def test_realistic_is_never_better_than_as_promised():
    gap = engine.replacement_gap(
        {"small": 5, "medium": 10, "large": 5}, W, 4, 1.0, Range(0.37, 0.5), YEARS_RANGE
    )
    ap, re_ = gap["as_promised"], gap["realistic"]
    for a, r in zip(ap["recovered_fraction"], re_["recovered_fraction"]):
        assert r["low"] <= a["low"] + 1e-12
        assert r["high"] <= a["high"] + 1e-12
    assert re_["unrecovered_service_years"].high >= ap["unrecovered_service_years"].high
    assert re_["unrecovered_service_years"].low >= ap["unrecovered_service_years"].low


def test_promised_recovers_within_horizon_while_realistic_does_not():
    # 3 promised per tree: 100% survival recovers, 37% (=1.11x) barely/never does in 40y slow growth
    gap = engine.replacement_gap({"large": 100}, W, 3, 1.0, Range(0.2, 0.3), YEARS_RANGE)
    assert gap["as_promised"]["recovery_year"]["worst_case"] is not None
    assert gap["realistic"]["recovery_year"]["best_case"] is None  # 3 * 0.3 = 0.9 < 1
    assert gap["realistic"]["recovery_year"]["worst_case"] is None


def test_replacement_gap_rejects_bad_horizon():
    with pytest.raises(ValueError):
        engine.replacement_gap({"large": 1}, W, 3, 1.0, 0.5, YEARS_RANGE, horizon=0)


# ---------------------------------------------------------------- orchestration (real data)
def test_calculate_pune_returns_ranges_and_sources(city_profiles, services_data):
    out = engine.calculate(
        {"small": 100, "medium": 300, "large": 129},
        city_profiles["cities"]["pune"], services_data, promised_ratio=10,
    )
    assert set(out["annual_loss"]) == set(engine.SERVICES)
    for service, v in out["annual_loss"].items():
        assert v["low"] < v["high"], service
        assert v["unit"]
        assert v["sources"] and all(s["source"] and s["verification_status"] for s in v["sources"])
    assert out["inputs"]["total_trees"] == 529
    gap = out["replacement_gap"]
    assert gap["as_promised"]["survival"] == {"low": 1.0, "high": 1.0}
    assert gap["realistic"]["survival"] == {"low": 0.37, "high": 0.63}
    assert gap["sources"]["survival_realistic"]["source"]


def test_total_unit_wording():
    assert engine.total_unit("kg CO2 sequestered per tree per year") == (
        "kg CO2 sequestered per year, all felled trees combined"
    )
    assert "all felled trees combined" in engine.total_unit("something else")


def test_calculate_units_are_totals(city_profiles, services_data):
    out = engine.calculate({"large": 3}, city_profiles["cities"]["pune"], services_data)
    for v in out["annual_loss"].values():
        assert "per tree" not in v["unit"]


def test_calculate_mumbai_uses_city_survival(city_profiles, services_data):
    out = engine.calculate({"large": 50}, city_profiles["cities"]["mumbai"], services_data, promised_ratio=4)
    assert out["replacement_gap"]["realistic"]["survival"] == {"low": 0.35, "high": 0.5}
    # With 4 per tree and ~0.35-0.5 survival (1.4-2.0x), full recovery is possible only late
    re_ = out["replacement_gap"]["realistic"]["recovery_year"]
    ap = out["replacement_gap"]["as_promised"]["recovery_year"]
    assert ap["best_case"] is not None
    assert re_["best_case"] is None or re_["best_case"] >= ap["best_case"]


def test_calculate_scales_with_tree_count(city_profiles, services_data):
    city = city_profiles["cities"]["pune"]
    one = engine.calculate({"large": 100}, city, services_data)["annual_loss"]["carbon"]
    two = engine.calculate({"large": 200}, city, services_data)["annual_loss"]["carbon"]
    assert two["low"] == pytest.approx(2 * one["low"], rel=0.02)
    assert two["high"] == pytest.approx(2 * one["high"], rel=0.02)


def test_calculate_overrides_and_validation(city_profiles, services_data):
    city = city_profiles["cities"]["pune"]
    out = engine.calculate(
        {"large": 10}, city, services_data, promised_ratio=6, promised_survival=0.9,
        realistic_survival={"low": 0.4, "high": 0.5}, growth_class="fast", horizon=30,
    )
    assert out["inputs"]["growth_class"] == "fast"
    assert out["replacement_gap"]["horizon_years"] == 30
    assert len(out["replacement_gap"]["realistic"]["recovered_fraction"]) == 31
    assert out["replacement_gap"]["as_promised"]["survival"] == {"low": 0.9, "high": 0.9}
    with pytest.raises(ValueError):
        engine.calculate({"large": 10}, city, services_data, growth_class="giant")
    with pytest.raises(ValueError):
        engine.calculate({"large": 10}, city, services_data, realistic_survival=(0.5, 1.5))
    with pytest.raises(ValueError):
        engine.calculate({"large": 10}, city, services_data, promised_ratio=-1)
    with pytest.raises(ValueError):
        engine.calculate({}, city, services_data)


def test_calculate_is_pure(city_profiles, services_data):
    import copy

    city = city_profiles["cities"]["pune"]
    c_before, s_before = copy.deepcopy(city), copy.deepcopy(services_data)
    engine.calculate({"small": 3, "large": 3}, city, services_data)
    assert city == c_before and services_data == s_before


def test_output_has_no_nan_or_inf(city_profiles, services_data):
    out = engine.calculate({"small": 7, "medium": 3, "large": 1}, city_profiles["cities"]["mumbai"], services_data)
    for v in out["annual_loss"].values():
        assert math.isfinite(v["low"]) and math.isfinite(v["high"])
    for p in out["replacement_gap"]["realistic"]["recovered_fraction"]:
        assert math.isfinite(p["low"]) and math.isfinite(p["high"])
