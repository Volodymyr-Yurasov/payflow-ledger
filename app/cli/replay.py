import click
from flask.cli import AppGroup

from app.extensions import services
from app.models import EventStatus
from app.services.replay import replay_events

events_cli = AppGroup("events", help="Inspect and replay stored webhook events.")


@events_cli.command("replay")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    type=click.Choice([EventStatus.REJECTED, EventStatus.IGNORED]),
    default=[EventStatus.REJECTED],
    show_default=True,
    help="Which stored events to re-apply (repeatable).",
)
@click.option("--type", "event_type", help="Only events of this type.")
@click.option("--id", "event_id", help="Only this event id.")
def replay(statuses, event_type, event_id):
    """Re-apply quarantined/ignored events with the current code."""
    results = replay_events(
        services().tx, statuses=statuses, event_type=event_type, event_id=event_id
    )
    for r in results:
        line = f"{r.event_id}: {r.old_status} -> {r.new_status}"
        click.echo(f"{line} ({r.error})" if r.error else line)
    click.echo(f"replayed {len(results)} event(s)")
