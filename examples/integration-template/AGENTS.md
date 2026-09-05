## DevSim Preview Runtime

This repository uses DevSim as the canonical DEV/Preview runtime.
Before manually creating mock data or direct runtime database mutations:
1. run `devsim project status --json`
2. run `devsim doctor --json`
3. use a canonical preview profile
4. use deterministic seed `42` unless another seed is required
5. drive runtime behavior through real application paths
6. verify API/UI state when applicable
7. inspect the DevSim run artifact
8. stop the preview when finished

Do not commit `.devsim/` runtime artifacts.
Do not use DevSim against production.
