# Addendum 01 — Backend-Aware Enrichment & Knowledge Base (SAP and non-SAP)

Extends `build-specification.txt`. Priority: required for v1 usefulness in enterprise (especially SAP) environments.

## Requirement

1. **Domain-agnostic intake.** IntakePilot must handle asks that touch SAP systems (ECC/S4, BW, etc.) and non-SAP systems equally. Business users must never need SAP or any backend knowledge to get something done. This is an extension of the existing `askable: false` rule: system-level detail is *never* asked of the requester — it is discovered.

2. **Backend Metadata Discovery (enrichment agent).** When an ask implies backend data (e.g. "pull order info", "goods details for a product"), a discovery step runs *after confirmation, before routing*:
   - Resolves business terms to backend entities via the glossary (e.g. "order" → `VBAK/VBAP` in SAP, or an `orders` table in a non-SAP system).
   - Reads the target system's **customizations** through a connector interface: custom columns, SAP Z-fields/appends, custom tables, validation rules — things the business user does not and should not know about.
   - Attaches findings to the Requirement Object's tech enrichment (`nfr` / `affected_systems` / a new `backend_context` slot with `provenance=retrieved`), so the ticket the assigned team receives contains everything needed to decide and build without a second interrogation of the requester.

3. **Connector interface (provider pattern, per Section 5).** A new protocol alongside the existing three — no SDK imports outside `core/providers/`:

   ```python
   class SystemConnector(Protocol):
       name: str                      # "sap_s4", "postgres_app_db", "rest_generic"
       async def resolve_entity(self, term: str) -> list[EntityMatch]
       async def describe_entity(self, entity: str) -> EntitySchema
           # EntitySchema includes standard fields AND customizations:
           # custom columns/Z-fields with name, type, description, owner team
       async def list_customizations(self, area: str | None = None) -> list[Customization]
   ```

   Local/default implementation: a **mock/fixture connector** driven by YAML fixtures (e.g. `core/schemas/systems/*.yaml`) describing example SAP and non-SAP systems with customized columns — so the demo shows the full flow offline. Real SAP (OData/RFC) and JDBC/REST connectors are cloud-path work.

4. **Knowledge base, not one-off lookups.** Every discovery result is persisted so the system never re-learns the same fact:
   - New table `system_kb` (mirrors glossary pattern): `entity`, `system`, `schema JSONB` (incl. customizations), `evidence_count`, `last_refreshed`, embedding for retrieval.
   - Discovered mappings feed the existing glossary and the RETRIEVE step of the Gap Resolution Ladder, so future intakes infer `affected_systems` and `backend_context` without asking anyone.
   - A recurring refresh job (fits the Section 7.3 nightly distillation slot) re-scans connectors for changed customizations and updates `system_kb`; stale entries are demoted per the existing staleness policy.

5. **Invariants (extend Section 11).**
   - Backend/customization detail never reaches the Question Composer; it is discovered or left to tech enrichment.
   - Discovery results carry provenance (`retrieved`, source = connector + entity) and are auditable in the ticket.
   - Only confirmed/human-validated mappings raise `evidence_count`; raw discovery stays marked unverified until a routed ticket's team touches it without correction.

## Demo acceptance

Ask: "I need a report of goods details for product line X with the order info" — the confirmed requirement routes with `backend_context` listing the relevant order/material entities *including* a customized column (e.g. `ZZ_PRIORITY_CODE` from the fixture SAP system) that the requester was never asked about; the routed ticket shows it under a "System context (auto-discovered)" section.
