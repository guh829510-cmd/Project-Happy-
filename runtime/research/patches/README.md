# Upstream patches

Minimal fixes for defects in released packages. Applied to the installed
package, not vendored — we copy no upstream source.

## gpt-researcher 0.16.0 — missing typing imports

`gpt_researcher/actions/query_processing.py` uses `Any`, `Dict`, `List` and
`Optional` without importing them, so **the package cannot be imported at all**:

    NameError: name 'Any' is not defined

Present in the release and in upstream HEAD. Apply after install:

```bash
python - <<'PY'
from pathlib import Path
import gpt_researcher, os
f = Path(os.path.dirname(gpt_researcher.__file__)) / "actions" / "query_processing.py"
s = f.read_text()
if "from typing import" not in s.split("def ")[0]:
    f.write_text(s.replace(
        "import json_repair\n",
        "import json_repair\nfrom typing import Any, Dict, List, Optional\n", 1))
    print("patched", f)
PY
```

Report upstream rather than carrying this indefinitely.
