# Technical note 01 -- layered data architecture

## What we built

```
data/
  raw/         # source-of-truth JSON, gzipped, immutable
  bronze/      # raw -> typed parquet, partitioned by season
  silver/      # dim_* + fact_* cleaned tables
  gold/        # feature tables for modelling
  reference/   # curated CSVs (venue capacity, arena geo)
  warehouse.db # SQLite that mirrors silver + gold for ad-hoc SQL
ingest_manifest.parquet  # provenance
```

## Why five layers

1. **Raw is cheap and valuable.** Keeping raw payloads lets us re-parse when the schema changes or
   a bug is found. Losing raw is the most expensive mistake in data engineering.
2. **Bronze is cheap structure.** Parquet with proper types is ~10x smaller than JSON and
   columnar-readable. It's the first rung where `pandas.read_parquet` just works.
3. **Silver is where joins and dedup happen.** This is the "clean" layer that a business user
   would query. No project-specific features live here.
4. **Gold is project-specific.** Everything that is HCA-relevant (Elo, attendance buckets,
   days_rest) lives in gold so it can be recomputed independently of silver.
5. **SQLite warehouse** is a convenience for `pd.read_sql` from scripts and `datasette` browsing.

## Idempotency

The manifest records `(source, season, fetched_at, rows, hash)`. Re-running any phase is a no-op
unless the upstream raw payload changed.

## What we'd do differently

- Partition silver by season instead of writing one file per season. pyarrow supports it natively
  and makes appends cheaper.
- Move venue_capacity.csv into a `dim_venue_season` table in silver with a `source_url` column so
  the lineage is queryable from SQL.

## When to collapse layers

For datasets <1M rows (ours is 4,000 games x 10 seasons = 40k rows), we could skip bronze and go
directly raw -> silver. We kept bronze because it gave us a stable intermediate during iteration.
