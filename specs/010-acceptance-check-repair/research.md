# Research and decision

Production logs show HTTP 500 from comparing a timezone-naive SQLite timestamp and a timezone-aware newly committed model timestamp. SQLite storage does not retain timezone offsets for the configured model. Normalize both to UTC at the serialization boundary, preserving the timestamp rather than interpreting it as local server time. A schema change is unnecessary. Release this independent defect correction before publication infrastructure because it does not require a new browser origin or COS cutover.
