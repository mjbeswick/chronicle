"""Chronicle entry point."""

import sys


def main() -> None:
    """Run Chronicle — TUI by default, CLI when a subcommand is given."""
    from app.cli import SUBCOMMANDS

    argv = sys.argv[1:]
    if argv and (argv[0] in SUBCOMMANDS or argv[0].startswith("-")):
        from app.cli import run
        sys.exit(run(argv))

    from app.app import ChronicleApp
    ChronicleApp().run()


if __name__ == "__main__":
    main()
