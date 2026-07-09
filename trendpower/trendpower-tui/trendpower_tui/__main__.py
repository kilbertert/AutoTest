"""Entry point: `trendpower` (no args -> TUI, with args -> CLI subcommands).

This is the Python equivalent of `src/cli/index.tsx`.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1:
        # CLI mode: hand off to click subcommands.
        from .commands import cli

        cli()
    else:
        # TUI mode: launch Textual app.
        from .app import TrendpowerApp

        TrendpowerApp().run()


if __name__ == "__main__":
    main()
