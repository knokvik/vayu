"""Tree Loss Receipt - FastAPI backend."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from .data import load_city_profiles, load_services_ranges
from .schemas import CalculateRequest, SurvivalRange

app = FastAPI(
    title="Tree Loss Receipt API",
    version="0.2.0",
    description=(
        "Local-first API that quantifies annual urban tree-loss impacts as ranges and "
        "compares 'as promised' with 'realistic' replacement recovery."
    ),
)

# The Vite dev server runs on a different local port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

RECEIPT_NOTES = [
    "All figures are ranges (low, high), never precise single values.",
    "Per-tree service ranges are indicative and marked 'indicative, to be verified' where not checked against a primary source; see each entry's verification_status.",
    "Replacement-gap results come from a simple model (linear sapling growth, linear survival decline over the 7-year establishment period) and are not forecasts.",
    "This is not legal advice.",
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/city-profiles")
def city_profiles() -> dict[str, Any]:
    """City profiles, survival presets and growth classes, loaded from local JSON."""
    profiles = load_city_profiles()
    services = load_services_ranges()
    return {
        "disclaimer": profiles["disclaimer"],
        "survival_presets": profiles["survival_presets"],
        "default_survival_as_promised": profiles["default_survival_as_promised"],
        "cities": profiles["cities"],
        "growth_classes": services["growth_classes"],
        "size_classes": services["size_classes"],
    }


def _survival_value(value: Any) -> Any:
    if isinstance(value, SurvivalRange):
        return (value.low, value.high)
    return value


@app.post("/calculate")
def calculate(req: CalculateRequest) -> dict[str, Any]:
    profiles = load_city_profiles()
    services = load_services_ranges()

    city = profiles["cities"].get(req.city.lower())
    if city is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown city '{req.city}'. Available: {sorted(profiles['cities'])}",
        )

    realistic = _survival_value(req.realistic_survival)
    if req.survival_preset is not None:
        preset = profiles["survival_presets"].get(req.survival_preset)
        if preset is None:
            raise HTTPException(
                status_code=422,
                detail=f"unknown survival_preset '{req.survival_preset}'. "
                f"Available: {sorted(profiles['survival_presets'])}",
            )
        realistic = (preset["low"], preset["high"])

    try:
        if req.tree_counts is not None:
            counts = req.tree_counts.model_dump()
        else:
            counts = engine.counts_from_mix(req.total_trees, req.size_mix.model_dump())
        result = engine.calculate(
            counts,
            city,
            services,
            promised_ratio=req.promised_ratio,
            promised_survival=_survival_value(req.promised_survival),
            realistic_survival=realistic,
            growth_class=req.growth_class,
            horizon=req.horizon_years,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result["city"] = {
        "id": city["id"],
        "name": city["name"],
        "rainfall": city["rainfall"],
        "heat_context": city["heat_context"],
        "compensatory_planting": city["compensatory_planting"],
    }
    result["notes"] = RECEIPT_NOTES
    return result
