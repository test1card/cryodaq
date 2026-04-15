# Overlay Design System Primitives

Phase I foundational shell widgets for Phase UI-1 v2:

- `ModalCard` — centered modal card with dim backdrop and 3 close paths
- `DrillDownBreadcrumb` — compact breadcrumb/back bar for overlay headers
- `BentoGrid` — 12-column layout container for future Bento tiles

## Minimal usage

```python
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from cryodaq.gui.shell.overlays._design_system import (
    BentoGrid,
    DrillDownBreadcrumb,
    ModalCard,
)

modal = ModalCard(max_width=1100)
content = QWidget()
layout = QVBoxLayout(content)
layout.addWidget(DrillDownBreadcrumb("Аналитика"))
grid = BentoGrid()
grid.add_tile(QLabel("Tile A"), col=0, row=0, col_span=6)
grid.add_tile(QLabel("Tile B"), col=6, row=0, col_span=6)
layout.addWidget(grid)
modal.set_content(content)
```

For visual review, run:

```bash
.venv/bin/python -m cryodaq.gui.shell.overlays._design_system._showcase
```

