# Venue/Team Reconciliation Gotchas

1. **Venue Codes vs Reference**: The live API uses actual venue codes (e.g., `AUM`, `AVH1`) whereas our mock data used synthetic codes (`V_RM`, `V_BC`).
2. **Missing Venues**: The `venues` endpoint doesn't always return all venues used in historical games. We solved this by extracting venue data directly from the `game_metadata` response as a fallback to populate `dim_venue_season`.
3. **Team IDs in Boxscores**: The `boxscore` endpoint doesn't always include the `team_id` at the top level. We had to cross-reference the `game_metadata` file to map `local` and `road` sides to their respective `team_id`s.
