# Rate-Limit Handling & Checkpoint Design

When pulling 10 seasons of live EuroLeague data (~3,100 games + boxscores), we hit the API rate limit (5 req/s).

## Solution
1. **Tenacity**: Used `tenacity` for exponential backoff on HTTP errors.
2. **Session Level Rate Limiting**: Implemented a `_wait_for_rate_limit()` function that enforces a minimum 0.2s interval between requests globally across the `requests.Session`.
3. **Idempotent Caching**: Each endpoint response is cached to `data/lake/raw/live/{endpoint}/{season}/{key}.json.gz`. If the file exists, the network call is skipped. This acts as our resume-checkpoint.
