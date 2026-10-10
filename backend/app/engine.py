"""Calculation engine for the Tree Loss Receipt.

Pure functions only: no file or network access, no global state. Callers pass in
the data (city profile, service ranges) so everything here is easy to test.

Conventions
-----------
* Every quantity that is uncertain is a ``Range(low, high)``. Nothing returns a
  single precise number for an impact figure.
* ``low`` is always the cautious end for the *recovery* of replacement trees
  (slow growth, low survival) and the smaller end for annual losses.
* Size classes are ``small``, ``medium`` and ``large``.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, NamedTuple, Sequence

SIZE_CLASSES: tuple[str, ...] = ("small", "medium", "large")
SERVICES: tuple[str, ...] = ("cooling", "rainwater", "air", "carbon")

DEFAULT_HORIZON_YEARS = 40
# Maharashtra Act s.8(5A): planted trees must survive a minimum of seven years.
DEFAULT_ESTABLISHMENT_YEARS = 7
# Number of significant figures kept on reported impact ranges, to avoid false precision.
DEFAULT_SIG_FIGS = 2


class Range(NamedTuple):
    """An inclusive (low, high) range."""

    low: float
    high: float

    def to_dict(self) -> dict[str, float]:
        return {"low": self.low, "high": self.high}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def make_range(low: float, high: float) -> Range:
    """Build a Range, validating ``low <= high``."""
    if low > high:
        raise ValueError(f"range low ({low}) must be <= high ({high})")
    return Range(float(low), float(high))


def as_range(value: Any) -> Range:
    """Coerce a Range, (low, high) pair, ``{"low","high"}`` dict, or scalar to a Range."""
    if isinstance(value, Range):
        return value
    if isinstance(value, Mapping):
        return make_range(value["low"], value["high"])
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return make_range(value[0], value[1])
    if isinstance(value, (int, float)):
        return make_range(value, value)
    raise TypeError(f"cannot interpret {value!r} as a range")


def _round_sig(value: float, sig: int, direction: str) -> float:
    """Round to ``sig`` significant figures, 'down' (floor) or 'up' (ceil)."""
    if value == 0:
        return 0.0
    exponent = math.floor(math.log10(abs(value)))
    factor = 10 ** (sig - 1 - exponent)
    scaled = value * factor
    # Guard against float noise (e.g. 2.9999999999 -> 3).
    nearest = round(scaled)
    if math.isclose(scaled, nearest, rel_tol=1e-9, abs_tol=1e-9):
        scaled = float(nearest)
    rounded = math.floor(scaled) if direction == "down" else math.ceil(scaled)
    return float(f"{rounded / factor:.12g}")  # strip float noise such as 1999999.9999999998


def round_range(r: Range, sig: int = DEFAULT_SIG_FIGS) -> Range:
    """Widen a range outwards to ``sig`` significant figures (low down, high up)."""
    r = as_range(r)
    return Range(_round_sig(r.low, sig, "down"), _round_sig(r.high, sig, "up"))


def validate_counts(counts: Mapping[str, float]) -> dict[str, float]:
    """Return a clean ``{small, medium, large}`` count mapping (missing -> 0)."""
    unknown = set(counts) - set(SIZE_CLASSES)
    if unknown:
        raise ValueError(f"unknown size classes: {sorted(unknown)}")
    clean: dict[str, float] = {}
    for size in SIZE_CLASSES:
        n = counts.get(size, 0)
        if n < 0:
            raise ValueError(f"tree count for '{size}' must be >= 0")
        clean[size] = float(n)
    if sum(clean.values()) <= 0:
        raise ValueError("at least one tree is required")
    return clean


def counts_from_mix(total_trees: int, mix: Mapping[str, float]) -> dict[str, int]:
    """Split ``total_trees`` into size-class counts using mix fractions or percentages.

    ``mix`` values are relative weights (they need not sum to 1). Uses the
    largest-remainder method so the counts always sum to ``total_trees``.
    """
    if total_trees <= 0:
        raise ValueError("total_trees must be > 0")
    weights = {s: float(mix.get(s, 0.0)) for s in SIZE_CLASSES}
    if any(w < 0 for w in weights.values()):
        raise ValueError("mix weights must be >= 0")
    total_w = sum(weights.values())
    if total_w <= 0:
        raise ValueError("mix must have a positive weight")
    exact = {s: total_trees * w / total_w for s, w in weights.items()}
    counts = {s: int(math.floor(v)) for s, v in exact.items()}
    remainder = total_trees - sum(counts.values())
    order = sorted(SIZE_CLASSES, key=lambda s: exact[s] - counts[s], reverse=True)
    for s in order[:remainder]:
        counts[s] += 1
    return counts


# --------------------------------------------------------------------------- #
# Service table
# --------------------------------------------------------------------------- #
def build_service_table(entries: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Turn the flat ``services`` list from services_ranges.json into
    ``table[service][size_class] = {"range": Range, "unit", "source", "note", "verification_status"}``.
    """
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for e in entries:
        service, size = e["service"], e["size_class"]
        if size not in SIZE_CLASSES:
            raise ValueError(f"unknown size class '{size}' in service entry {e.get('id')}")
        table.setdefault(service, {})[size] = {
            "range": make_range(e["low"], e["high"]),
            "unit": e["unit"],
            "source": e["source"],
            "note": e.get("note", ""),
            "verification_status": e.get("verification_status", "unknown"),
        }
    for service, by_size in table.items():
        missing = set(SIZE_CLASSES) - set(by_size)
        if missing:
            raise ValueError(f"service '{service}' missing size classes: {sorted(missing)}")
    return table


def total_unit(per_tree_unit: str) -> str:
    """Convert a per-tree unit ('kg CO2 ... per tree per year') into an all-trees unit."""
    marker = " per tree per year"
    if marker in per_tree_unit:
        return per_tree_unit.replace(marker, " per year, all felled trees combined")
    return f"{per_tree_unit} (all felled trees combined)"


# --------------------------------------------------------------------------- #
# Annual loss
# --------------------------------------------------------------------------- #
def size_class_weights(table: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> dict[str, float]:
    """Relative service weight of each size class, with ``large`` = 1.0.

    For each service take the midpoint of each class range divided by the large
    class midpoint, then combine services with a geometric mean. These are the
    *size-class multipliers* used to convert a mixed set of trees into
    "large-tree equivalents" for the replacement simulation. They are derived
    entirely from the service ranges, so they carry the same uncertainty.
    """
    ratios: dict[str, list[float]] = {s: [] for s in SIZE_CLASSES}
    for by_size in table.values():
        mids = {s: sum(by_size[s]["range"]) / 2.0 for s in SIZE_CLASSES}
        if mids["large"] <= 0:
            continue
        for s in SIZE_CLASSES:
            ratios[s].append(mids[s] / mids["large"])
    weights: dict[str, float] = {}
    for s in SIZE_CLASSES:
        vals = ratios[s]
        if not vals:
            raise ValueError("service table is empty")
        weights[s] = math.exp(sum(math.log(v) for v in vals) / len(vals))
    # Normalise so large is exactly 1 (it already is, but avoid float drift).
    scale = weights["large"]
    return {s: w / scale for s, w in weights.items()}


def annual_loss(
    counts: Mapping[str, float],
    table: Mapping[str, Mapping[str, Mapping[str, Any]]],
    multipliers: Mapping[str, float] | None = None,
) -> dict[str, Range]:
    """Annual loss range for each service across the felled trees.

    ``low`` sums every tree at its class's low value and ``high`` at its high
    value, so the output is a genuine (low, high) envelope. ``multipliers`` is an
    optional per-size-class scaling (default 1.0), e.g. 0.7 for stressed street
    trees. Output is NOT rounded here; use :func:`round_range` for display.
    """
    counts = validate_counts(counts)
    mult = {s: 1.0 for s in SIZE_CLASSES}
    if multipliers:
        for s, m in multipliers.items():
            if s not in SIZE_CLASSES:
                raise ValueError(f"unknown size class '{s}' in multipliers")
            if m < 0:
                raise ValueError("multipliers must be >= 0")
            mult[s] = float(m)
    result: dict[str, Range] = {}
    for service, by_size in table.items():
        low = sum(counts[s] * mult[s] * by_size[s]["range"].low for s in SIZE_CLASSES)
        high = sum(counts[s] * mult[s] * by_size[s]["range"].high for s in SIZE_CLASSES)
        result[service] = Range(low, high)
    return result


# --------------------------------------------------------------------------- #
# Replacement gap
# --------------------------------------------------------------------------- #
def survival_fraction(
    year: float,
    final_survival: float,
    establishment_years: float = DEFAULT_ESTABLISHMENT_YEARS,
) -> float:
    """Share of replacement trees alive at ``year`` after planting.

    Starts at 100% and declines linearly to ``final_survival`` over the
    establishment period (7 years, matching the legal monitoring period), then
    stays flat.
    """
    if not 0.0 <= final_survival <= 1.0:
        raise ValueError("survival must be between 0 and 1")
    if year < 0:
        raise ValueError("year must be >= 0")
    if establishment_years <= 0:
        return final_survival
    progress = min(year / establishment_years, 1.0)
    return 1.0 - (1.0 - final_survival) * progress


def growth_weight(
    age: float,
    years_to_class: Mapping[str, float],
    weights: Mapping[str, float],
) -> float:
    """Service weight (large tree = 1.0) of a surviving replacement tree of ``age`` years.

    Linear interpolation through (0, 0) -> (years to small, w_small) ->
    (years to medium, w_medium) -> (years to large, w_large). Constant after that.
    """
    if age < 0:
        raise ValueError("age must be >= 0")
    points = [(0.0, 0.0)] + [(float(years_to_class[s]), float(weights[s])) for s in SIZE_CLASSES]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x1 < x0:
            raise ValueError("years to reach size classes must be increasing")
    if age >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if age <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (age - x0) / (x1 - x0)
    return points[-1][1]  # pragma: no cover


def recovery_curve(
    counts: Mapping[str, float],
    weights: Mapping[str, float],
    promised_ratio: float,
    final_survival: float,
    years_to_class: Mapping[str, float],
    horizon: int = DEFAULT_HORIZON_YEARS,
    establishment_years: float = DEFAULT_ESTABLISHMENT_YEARS,
) -> list[float]:
    """Recovered fraction of the felled trees' services for years 0..horizon (one corner case).

    ``1.0`` means the replacement trees now deliver as much as the felled trees
    did. The felled trees are held constant (they would also have kept growing,
    so this is slightly generous to the replacement scenario).
    """
    counts = validate_counts(counts)
    if promised_ratio < 0:
        raise ValueError("promised_ratio must be >= 0")
    total = sum(counts.values())
    baseline = sum(counts[s] * weights[s] for s in SIZE_CLASSES)
    if baseline <= 0:
        raise ValueError("baseline service weight must be > 0")
    planted = promised_ratio * total
    curve = []
    for year in range(horizon + 1):
        alive = planted * survival_fraction(year, final_survival, establishment_years)
        delivered = alive * growth_weight(year, years_to_class, weights)
        curve.append(delivered / baseline)
    return curve


def recovery_year(curve: Sequence[float]) -> int | None:
    """First year from which the recovered fraction stays >= 1.0 to the end of the curve.

    Returns ``None`` if full recovery is not reached within the horizon.
    """
    first: int | None = None
    for year in range(len(curve) - 1, -1, -1):
        if curve[year] >= 1.0 - 1e-12:
            first = year
        else:
            break
    return first


def unrecovered_service_years(curve: Sequence[float]) -> float:
    """Sum over each simulated year (excluding the final point) of the share of baseline service still missing.

    Reads as "years' worth of the felled trees' service that is never delivered".
    Years where replacements exceed the baseline do not offset earlier deficits.
    """
    return sum(max(0.0, 1.0 - v) for v in curve[:-1])


def _years_corner(years_range: Mapping[str, Sequence[float]], corner: str) -> dict[str, float]:
    """Pick the fast (index 0) or slow (index 1) years for each class."""
    idx = 0 if corner == "fast" else 1
    return {s: float(years_range[s][idx]) for s in SIZE_CLASSES}


def scenario_gap(
    counts: Mapping[str, float],
    weights: Mapping[str, float],
    promised_ratio: float,
    survival: Range,
    years_range: Mapping[str, Sequence[float]],
    horizon: int = DEFAULT_HORIZON_YEARS,
    establishment_years: float = DEFAULT_ESTABLISHMENT_YEARS,
) -> dict[str, Any]:
    """Simulate one scenario and return range-valued results.

    The low corner is slow growth + lowest survival; the high corner is fast
    growth + highest survival. Recovery is monotonic in both, so these two
    corners bound all other combinations.
    """
    survival = as_range(survival)
    low_curve = recovery_curve(
        counts, weights, promised_ratio, survival.low, _years_corner(years_range, "slow"),
        horizon, establishment_years,
    )
    high_curve = recovery_curve(
        counts, weights, promised_ratio, survival.high, _years_corner(years_range, "fast"),
        horizon, establishment_years,
    )
    # The year a scenario is recovered "at best" is the high corner; "at worst" the low corner.
    best_year = recovery_year(high_curve)
    worst_year = recovery_year(low_curve)
    return {
        "survival": survival,
        "recovered_fraction": [
            {"year": y, "low": low_curve[y], "high": high_curve[y]} for y in range(horizon + 1)
        ],
        "recovery_year": {"best_case": best_year, "worst_case": worst_year},
        "recovered_within_horizon": {"best_case": best_year is not None, "worst_case": worst_year is not None},
        "unrecovered_service_years": Range(
            unrecovered_service_years(high_curve), unrecovered_service_years(low_curve)
        ),
    }


def replacement_gap(
    counts: Mapping[str, float],
    weights: Mapping[str, float],
    promised_ratio: float,
    promised_survival: Any,
    realistic_survival: Any,
    years_range: Mapping[str, Sequence[float]],
    horizon: int = DEFAULT_HORIZON_YEARS,
    establishment_years: float = DEFAULT_ESTABLISHMENT_YEARS,
) -> dict[str, Any]:
    """Compare "As promised" against "Realistic" over a ``horizon``-year simulation."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    return {
        "horizon_years": horizon,
        "as_promised": scenario_gap(
            counts, weights, promised_ratio, as_range(promised_survival), years_range,
            horizon, establishment_years,
        ),
        "realistic": scenario_gap(
            counts, weights, promised_ratio, as_range(realistic_survival), years_range,
            horizon, establishment_years,
        ),
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def calculate(
    counts: Mapping[str, float],
    city: Mapping[str, Any],
    services_data: Mapping[str, Any],
    promised_ratio: float | None = None,
    promised_survival: Any = None,
    realistic_survival: Any = None,
    growth_class: str | None = None,
    horizon: int = DEFAULT_HORIZON_YEARS,
    sig_figs: int = DEFAULT_SIG_FIGS,
) -> dict[str, Any]:
    """Run the full calculation and return a JSON-friendly receipt payload.

    ``city`` is one entry of city_profiles.json ``cities``; ``services_data`` is
    the parsed services_ranges.json. Defaults come from the city profile.
    """
    counts = validate_counts(counts)
    table = build_service_table(services_data["services"])

    ratio = promised_ratio
    if ratio is None:
        ratio = city["compensatory_planting"]["default_promised_ratio"]
    if ratio < 0:
        raise ValueError("promised_ratio must be >= 0")

    promised = as_range(promised_survival if promised_survival is not None else 1.0)
    realistic = as_range(
        realistic_survival if realistic_survival is not None else city["survival"]["realistic"]
    )
    for name, r in (("promised_survival", promised), ("realistic_survival", realistic)):
        if not (0.0 <= r.low <= r.high <= 1.0):
            raise ValueError(f"{name} must lie within 0..1")

    growth = growth_class
    if growth is None:
        default_group_id = city["species_groups"]["default_group"]
        group = next(g for g in city["species_groups"]["groups"] if g["id"] == default_group_id)
        growth = group["growth_class"]
    classes = services_data["growth_classes"]["classes"]
    if growth not in classes:
        raise ValueError(f"unknown growth class '{growth}'")
    years_range = classes[growth]["years_to_size_class"]

    weights = size_class_weights(table)
    losses = annual_loss(counts, table)
    gap = replacement_gap(counts, weights, ratio, promised, realistic, years_range, horizon)

    annual: dict[str, Any] = {}
    for service, rng in losses.items():
        shown = round_range(rng, sig_figs)
        used = [s for s in SIZE_CLASSES if counts[s] > 0]
        annual[service] = {
            "low": shown.low,
            "high": shown.high,
            "unit": total_unit(table[service][used[0]]["unit"]),
            "sources": [
                {
                    "size_class": s,
                    "source": table[service][s]["source"],
                    "verification_status": table[service][s]["verification_status"],
                }
                for s in used
            ],
        }

    def scenario_out(sc: dict[str, Any]) -> dict[str, Any]:
        out = dict(sc)
        out["survival"] = sc["survival"].to_dict()
        out["unrecovered_service_years"] = round_range(sc["unrecovered_service_years"], sig_figs).to_dict()
        return out

    return {
        "inputs": {
            "city": city["id"],
            "tree_counts": counts,
            "total_trees": sum(counts.values()),
            "promised_ratio": ratio,
            "growth_class": growth,
            "horizon_years": horizon,
        },
        "annual_loss": annual,
        "replacement_gap": {
            "horizon_years": gap["horizon_years"],
            "as_promised": scenario_out(gap["as_promised"]),
            "realistic": scenario_out(gap["realistic"]),
            "replacement_trees_promised": ratio * sum(counts.values()),
            "size_class_weights": weights,
            "growth_years": years_range,
            "sources": {
                "growth": {
                    "source": services_data["growth_classes"]["note"],
                    "verification_status": services_data["growth_classes"]["verification_status"],
                },
                "survival_realistic": {
                    "source": city["survival"]["source"],
                    "verification_status": city["survival"]["verification_status"],
                },
                "survival_as_promised": {
                    "source": "User-stated promise, or default of 100% survival.",
                    "verification_status": "assumption_not_literature",
                },
            },
        },
    }
