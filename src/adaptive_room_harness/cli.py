from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="room",
    help="Adaptive Room Harness CLI.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Show the installed version."""
    from adaptive_room_harness import __version__

    console.print(__version__)


@app.command()
def init(
    workspace: str = typer.Option(..., help="Workspace path for the room."),
    task: str = typer.Option(..., help="Task summary for the room."),
) -> None:
    """Create a local task room.

    This command is a placeholder for the first implementation slice.
    """

    console.print("[bold]Room init planned[/bold]")
    console.print(f"workspace: {workspace}")
    console.print(f"task: {task}")

