"""Fixture connector — the local/default SystemConnector implementation.

Driven by YAML fixtures under core/schemas/systems/*.yaml, each describing one
example system (SAP or non-SAP) with entities, synonyms, standard fields, and
customizations. Lets the full backend-discovery flow run and demo offline;
real SAP OData/RFC and JDBC/REST connectors implement the same protocol.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.providers.connector.base import (Customization, EntityMatch,
                                            EntitySchema, FieldDef)


class FixtureConnector:
    def __init__(self, fixture_path: str | Path):
        self._path = Path(fixture_path)
        self.reload()

    def reload(self) -> None:
        raw = yaml.safe_load(self._path.read_text())
        self.name: str = raw["system"]
        self.label: str = raw.get("label", self.name)
        self.kind: str = raw.get("kind", "generic")
        self._entities: dict[str, dict] = raw.get("entities", {})

    async def resolve_entity(self, term: str) -> list[EntityMatch]:
        """Exact match of the term against entity keys, labels, and synonyms
        (case-insensitive). Deterministic, so tests and the demo are exact."""
        low = term.strip().lower()
        if not low:
            return []
        matches = []
        for key, ent in self._entities.items():
            names = {key.lower(), str(ent.get("label", "")).lower(),
                     *(str(s).lower() for s in ent.get("synonyms", []))}
            if low in names:
                matches.append(EntityMatch(
                    system=self.name, entity=key,
                    label=ent.get("label", key), matched_term=term))
        return matches

    async def describe_entity(self, entity: str) -> EntitySchema:
        ent = self._entities.get(entity)
        if ent is None:
            raise KeyError(f"{self.name}: unknown entity {entity!r}")
        return EntitySchema(
            system=self.name,
            system_label=self.label,
            entity=entity,
            label=ent.get("label", entity),
            backend_name=ent.get("backend_name", entity),
            description=ent.get("description", ""),
            synonyms=[str(s) for s in ent.get("synonyms", [])],
            fields=[FieldDef(**f) for f in ent.get("standard_fields", [])],
            customizations=[
                Customization(**{**c, "entity": entity,
                                 "area": ent.get("area", "")})
                for c in ent.get("customizations", [])])

    async def list_customizations(self, area: str | None = None) -> list[Customization]:
        out: list[Customization] = []
        for key, ent in self._entities.items():
            if area and ent.get("area") != area:
                continue
            for c in ent.get("customizations", []):
                out.append(Customization(**{**c, "entity": key,
                                            "area": ent.get("area", "")}))
        return out


def load_fixture_connectors(directory: str | Path) -> list[FixtureConnector]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return [FixtureConnector(p) for p in sorted(directory.glob("*.yaml"))]
