# Research
Serving fd191e5; origin/main is older fadfefd. Original workspace has unrelated edits, preserved. CPU idle, ~1.5GiB available RAM; disk95% (3.2GiB free) requires build-capacity planning.
Three server-side snapshots: 461/1809/363ms. Seven catalogs spent2.494s in COS workers of2.628s total; DB transactions89ms are secondary. Five/six historic project.updated events cause seven/eight overlapping details (mount+stream-open+history); requestSequence discards earlier successes.
Initial browser probe incorrectly matched the prior heading on two navigations; rejected. Corrected probe matches target title and reruns.
Decision: coalesced reads, first success application, persisted cursor filtering. Request-local manifest reuse removes duplicate immutable downloads without changing future request failure semantics. One read transaction captures consistent owner/head/provenance with full schema/journal validation.
Rejected: raising concurrency (amplifies workers); schema caching (misses journal tamper); cross-request TTL cache (changes freshness/deletion); full API split (unnecessary contract expansion for measured cause).
