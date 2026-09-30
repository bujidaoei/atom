# Data model
CommandReceipt: project_id + key composite primary key, digest, response_json, created_at. Project ownership authorizes receipt access; cascade on deletion. Existing Run stores each candidate retry separately; RaceHeat points to latest run and cumulative usage/time. No existing columns changed.
