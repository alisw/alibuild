package: tracking-env
version: "1.0"
track_env:
  TRACKED_ENV: echo "$TRACKED_ENV"
---
echo Building with $TRACKED_ENV
