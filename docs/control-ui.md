# Preview Control UI

The root page served by `devsim serve` is a deliberately small HTML interface for
controlling the simulation. It is not a replacement for the application UI.

It shows project and environment identity, runtime status, scenario, seed, clock
speed, virtual time, event counters, heartbeat, current run ID, and a compact run
timeline. Reset, seed, start, pause, resume, and stop are available from the same
page.

The page consumes the same JSON API documented in `control-api.md`, so an AI
coding agent can use the API directly and use the UI for visual confirmation.
