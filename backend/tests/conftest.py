import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="session")
def services_data():
    return json.loads((DATA_DIR / "services_ranges.json").read_text())


@pytest.fixture(scope="session")
def city_profiles():
    return json.loads((DATA_DIR / "city_profiles.json").read_text())


@pytest.fixture()
def toy_entries():
    """A tiny hand-made service table so unit tests do not depend on real data."""

    def entry(service, size, low, high):
        return {
            "id": f"{service}_{size}", "service": service, "size_class": size,
            "unit": f"{service}-unit", "low": low, "high": high,
            "source": f"toy source for {service}", "note": "", "verification_status": "toy",
        }

    entries = []
    for service in ("cooling", "carbon"):
        entries += [
            entry(service, "small", 10, 20),
            entry(service, "medium", 40, 80),
            entry(service, "large", 100, 200),
        ]
    return entries
