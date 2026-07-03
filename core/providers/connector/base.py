"""SystemConnector protocol (ADDENDUM-01) — the fourth provider protocol.

Backend metadata discovery: resolve business terms to backend entities, read
entity schemas INCLUDING customizations (custom columns, SAP Z-fields/appends,
custom tables) that the business user does not and should not know about.

Like the other three protocols, no SDK imports outside core/providers/ —
real SAP (OData/RFC) and JDBC/REST connectors are cloud-path implementations
of this same protocol.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class FieldDef(BaseModel):
    name: str
    type: str = ""
    description: str = ""


class Customization(BaseModel):
    """A customization the requester was never asked about: SAP Z-field,
    append structure, custom column, custom table, validation rule."""
    name: str
    type: str = ""
    description: str = ""
    owner_team: str = ""
    kind: str = "custom_column"    # z_field | append_field | custom_column
                                   # | custom_table | validation_rule
    entity: str = ""
    area: str = ""


class EntityMatch(BaseModel):
    system: str            # connector name, e.g. "sap_s4_demo"
    entity: str            # logical entity key, e.g. "sales_order"
    label: str = ""
    matched_term: str = ""
    score: float = 1.0


class EntitySchema(BaseModel):
    system: str
    system_label: str = ""
    entity: str
    label: str = ""
    backend_name: str = ""     # e.g. "VBAK/VBAP" or "public.orders"
    description: str = ""
    synonyms: list[str] = []   # business vocabulary that maps to this entity
    fields: list[FieldDef] = []
    customizations: list[Customization] = []


@runtime_checkable
class SystemConnector(Protocol):
    name: str                  # "sap_s4_demo", "fulfillment_db", "rest_generic"
    label: str

    async def resolve_entity(self, term: str) -> list[EntityMatch]: ...

    async def describe_entity(self, entity: str) -> EntitySchema: ...

    async def list_customizations(self, area: str | None = None) -> list[Customization]: ...
