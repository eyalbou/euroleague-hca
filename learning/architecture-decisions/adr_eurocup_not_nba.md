# ADR: Why EuroCup but not NBA in this round

## Context
We wanted to provide a cross-league context for the EuroLeague Home Court Advantage (HCA) to see if the magnitude is typical or unique.

## Decision
We decided to ingest and analyze EuroCup data but excluded NBA data for this phase.

## Rationale
1. **Same API**: EuroCup uses the exact same Swagger API structure as EuroLeague (competition code `U` instead of `E`). This means we can reuse the entire ingestion and processing pipeline with zero code changes, just by changing the `ELH_COMPETITION` environment variable.
2. **Time Budget**: The NBA API (`nba_api`) requires a completely different ingestion script, schema mapping, and validation process. It would take an estimated 6-8 hours to build and test.
3. **Sister League**: EuroCup is the second-tier European competition, making it a highly relevant "sister league" for comparison (similar rules, similar refereeing standards, but smaller arenas and less travel).
