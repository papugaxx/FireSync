import argparse
from dataclasses import asdict
from datetime import date, timedelta
import json
import sys

from .analytics import grid_calendar
from .calibration import calibrate_calendar
from .client import FirmsClient
from .config import load_settings
from .errors import ConfigurationError, PipelineError
from .service import SyncService, build_plan, select_sources
from .store import Store
from .types import PRODUCTS, Scope, utc_now


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=str, indent=2), flush=True)


def parse_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.") from None


def range_arguments(parser):
    parser.add_argument("--from", dest="date_from", type=parse_date)
    parser.add_argument("--to", dest="date_to", type=parse_date)
    parser.add_argument("--all-history", action="store_true",
                        help="Start at the earliest available date of the selected products.")
    parser.add_argument("--recent-days", type=int,
                        help="Load the last N complete UTC days, ending yesterday.")
    parser.add_argument("--include-today", action="store_true",
                        help="With --recent-days, include the current incomplete UTC day.")
    area = parser.add_mutually_exclusive_group()
    area.add_argument("--area", choices=["world"], default="world")
    area.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--scope-id")
    parser.add_argument("--scope-name")
    parser.add_argument("--sources", nargs="+", default=["auto"], choices=["auto", *PRODUCTS])
    parser.add_argument("--refresh", action="store_true", help="Reload even previously loaded dates.")
    parser.add_argument("--refresh-recent-days", type=int, default=3)


def build_parser():
    parser = argparse.ArgumentParser(description="NASA FIRMS API to SQLite. No web framework required.")
    parser.add_argument("--db", help="SQLite path; default: var/fires.sqlite3 next to this package.")
    parser.add_argument("--env-file", help="Configuration file; default: .env next to this package.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the database schema without contacting NASA.")
    commands.add_parser("doctor", help="Check local configuration without revealing the key.")
    commands.add_parser("availability", help="Fetch and cache current source availability from NASA.")
    plan = commands.add_parser("plan", help="Preview date coverage and pending daily slices.")
    range_arguments(plan)
    plan.add_argument("--cached", action="store_true", help="Use already cached availability, without NASA requests.")
    sync = commands.add_parser("sync", help="Fetch, validate and atomically save API observations.")
    range_arguments(sync)
    sync.add_argument("--batch-days", type=int, choices=range(1, 6), default=1)
    sync.add_argument("--max-requests", type=int, default=20,
                      help="Maximum Area requests per run; 0 means unlimited.")
    sync.add_argument("--min-interval", type=float, default=1.0)
    sync.add_argument("--quota-reserve", type=int, default=100)
    sync.add_argument("--min-free-gb", type=float, default=30,
                      help="Keep this many GiB free; pause safely if the reserve would be crossed.")
    status = commands.add_parser("status", help="Inspect database and recent jobs.")
    status.add_argument("--scope")
    rows = commands.add_parser("observations", help="Read observations for FastAPI or inspection.")
    rows.add_argument("--scope", required=True)
    rows.add_argument("--from", dest="date_from", type=parse_date, required=True)
    rows.add_argument("--to", dest="date_to", type=parse_date, required=True)
    rows.add_argument("--sensor", choices=["MODIS", "VIIRS"])
    rows.add_argument("--satellite")
    rows.add_argument("--limit", type=int, default=10)
    rows.add_argument("--offset", type=int, default=0)
    calendar = commands.add_parser("calendar", help="Calculate daily common-grid indices from the local database, without NASA requests.")
    calendar.add_argument("--scope", required=True)
    calendar.add_argument("--from", dest="date_from", type=parse_date, required=True)
    calendar.add_argument("--to", dest="date_to", type=parse_date, required=True)
    calendar.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    calibration = commands.add_parser("calibrate", help="Run a bounded regional scaling experiment with a chronological holdout.")
    calibration.add_argument("--scope", required=True)
    calibration.add_argument("--from", dest="date_from", type=parse_date, required=True)
    calibration.add_argument("--to", dest="date_to", type=parse_date, required=True)
    calibration.add_argument("--split", type=parse_date, required=True,
                             help="First held-out UTC day; earlier paired days are used for fitting.")
    calibration.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    return parser


def get_range(args, availability):
    if args.include_today and args.recent_days is None:
        raise ConfigurationError("Use --include-today together with --recent-days.")
    selected, _ = select_sources(args.sources)
    metadata = [row for code, row in availability.items() if code in selected]
    if not metadata:
        raise ConfigurationError("NASA reports no available dates for the selected sources.")
    if args.recent_days is not None:
        if args.all_history or args.date_from or args.date_to or not 1 <= args.recent_days <= 31:
            raise ConfigurationError("Use --recent-days 1..31 without other date options.")
        end = utc_now().date() - timedelta(days=0 if args.include_today else 1)
        start = end - timedelta(days=args.recent_days - 1)
    elif args.all_history:
        if args.date_from:
            raise ConfigurationError("Do not combine --all-history and --from.")
        start = min(row.min_date for row in metadata)
        end = args.date_to or min(utc_now().date(), max(row.max_date for row in metadata))
    else:
        if not args.date_from or not args.date_to:
            raise ConfigurationError("Use --from and --to, --recent-days, or --all-history.")
        start, end = args.date_from, args.date_to
    return start, end


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.env_file, args.db)
        store = Store(settings.db_path)
        if args.command == "doctor":
            emit({"python": sys.version.split()[0], "database": str(settings.db_path),
                  "database_exists": settings.db_path.is_file(), "map_key_configured": bool(settings.api_key),
                  "env_file": str(args.env_file or "data_pipeline/.env"),
                  "configuration_check_only": True})
            return 0
        if args.command == "init":
            store.initialize()
            store.save_scope(Scope.world())
            emit({"status": "initialized", "database": str(settings.db_path), **store.status()})
            return 0
        if args.command == "status":
            emit({**store.status(args.scope), "recent_jobs": store.list_jobs(limit=10)})
            return 0
        if args.command == "observations":
            emit(store.observations(args.scope, args.date_from, args.date_to,
                                    sensor=args.sensor, satellite=args.satellite,
                                    limit=args.limit, offset=args.offset))
            return 0
        if args.command in ("calendar", "calibrate"):
            report = grid_calendar(store, args.scope, args.date_from, args.date_to, bbox=args.bbox)
            emit(calibrate_calendar(report, args.split) if args.command == "calibrate" else report)
            return 0
        if args.command == "plan" and args.cached:
            metadata = store.get_availability()
            if not metadata:
                raise ConfigurationError("No cached availability. Obtain a MAP_KEY and run availability first.")
        else:
            client = FirmsClient(settings.api_key)
            service = SyncService(client, store)
            metadata = service.refresh_availability()
        if args.command == "availability":
            emit({code: {"from": row.min_date, "to": row.max_date} for code, row in metadata.items()})
            return 0
        if args.bbox:
            scope = Scope.from_bbox(args.bbox, args.scope_id, args.scope_name)
        elif args.scope_id or args.scope_name:
            scope = Scope(args.scope_id or "world", args.scope_name or "World", -180, -90, 180, 90)
        else:
            scope = Scope.world()
        start, end = get_range(args, metadata)
        store.save_scope(scope)
        plan = build_plan(store, scope, metadata, start, end, args.sources,
                          args.refresh, args.refresh_recent_days)
        if args.command == "plan":
            emit(plan.summary())
            return 0
        print("Plan:")
        emit(plan.summary())
        if not plan.tasks:
            if plan.skipped_units:
                emit({"status": "already_loaded", "cached_days": plan.skipped_units})
                return 0
            raise ConfigurationError("No available dates in this request. Inspect availability.")
        result = service.run(plan, batch_days=args.batch_days, max_requests=args.max_requests,
                             min_interval=args.min_interval, quota_reserve=args.quota_reserve,
                             min_free_gb=args.min_free_gb,
                             progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
        emit(result)
        return 0 if result["job"]["status"] == "completed" else 2
    except (PipelineError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped. Previously committed daily slices were preserved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
