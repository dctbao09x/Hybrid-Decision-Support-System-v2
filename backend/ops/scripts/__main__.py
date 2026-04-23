# backend/ops/scripts/__main__.py
"""
CLI entry point for ops scripts.

Usage:
    python -m backend.ops.scripts <command> [options]

Commands:
    health          Run health checks
    sla             Show SLA dashboard
    backup          Create backup
    restore         Restore from backup
    retention       Enforce retention policies
    status          Show pipeline status
    deps            Check dependencies
    updates         Check component update status
"""

import argparse
import asyncio
import json
import sys


def cmd_health(args):
    """Run health checks."""
    from backend.ops.monitoring.health import HealthCheckService
    service = HealthCheckService()
    service.register_check("disk_space", service.check_disk_space)
    service.register_check("memory", service.check_memory)
    service.register_check("data_dir", service.check_data_dir)
    service.register_check("scoring_engine", service.check_scoring_engine)
    result = asyncio.run(service.check_all())
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "healthy" else 1)


def cmd_sla(args):
    """Show SLA dashboard."""
    from backend.ops.monitoring.sla import SLAMonitor
    sla = SLAMonitor()
    print(json.dumps(sla.get_dashboard(), indent=2))


def cmd_backup(args):
    """Create or list backups."""
    from backend.ops.security.backup import BackupManager
    mgr = BackupManager()

    if args.action == "create":
        result = mgr.create_full_backup(label=args.label or "")
        print(json.dumps(result, indent=2))
    elif args.action == "list":
        backups = mgr.list_backups()
        for b in backups:
            print(f"  {b.get('name', '?'):40s}  {b.get('created_at', '?'):26s}  {b.get('files', '?')} files")
    elif args.action == "config":
        result = mgr.create_config_backup()
        print(json.dumps(result, indent=2))


def cmd_restore(args):
    """Restore from backup."""
    from backend.ops.security.backup import BackupManager
    mgr = BackupManager()

    if args.latest:
        backups = mgr.list_backups()
        if not backups:
            print("No backups found")
            sys.exit(1)
        name = backups[-1]["name"]
    else:
        name = args.name

    result = mgr.restore(name, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


def cmd_retention(args):
    """Enforce retention policies."""
    from backend.ops.maintenance.retention import RetentionManager
    mgr = RetentionManager(dry_run=args.dry_run)

    if args.status:
        print(json.dumps(mgr.get_status(), indent=2))
    else:
        result = mgr.enforce_all()
        print(json.dumps(result, indent=2))


def cmd_deps(args):
    """Check dependencies."""
    from backend.ops.maintenance.dependency_manager import DependencyManager
    mgr = DependencyManager()

    if args.action == "check":
        result = mgr.check_requirements()
        print(json.dumps(result, indent=2))
    elif args.action == "outdated":
        result = mgr.check_outdated()
        print(json.dumps(result, indent=2))
    elif args.action == "vulnerabilities":
        result = mgr.check_vulnerabilities()
        print(json.dumps(result, indent=2))
    elif args.action == "lock":
        path = mgr.generate_lockfile()
        print(f"Lockfile generated: {path}")


def cmd_updates(args):
    """Check component update status."""
    from backend.ops.maintenance.update_policy import UpdatePolicy
    policy = UpdatePolicy()
    print(json.dumps(policy.get_dashboard(), indent=2))


def cmd_status(args):
    """Show pipeline status."""
    from backend.ops.monitoring.health import HealthCheckService
    from backend.ops.monitoring.sla import SLAMonitor
    from backend.ops.monitoring.alerts import AlertManager
    from backend.ops.quality.source_reliability import SourceReliabilityScorer

    health = HealthCheckService()
    health.register_check("disk_space", health.check_disk_space)
    health.register_check("memory", health.check_memory)
    health.register_check("data_dir", health.check_data_dir)

    health_result = asyncio.run(health.check_all())

    sla = SLAMonitor()
    alerts = AlertManager()
    source = SourceReliabilityScorer()
    source.load()

    status = {
        "health": health_result,
        "sla": sla.get_dashboard(),
        "alerts_summary": alerts.get_summary(),
        "source_reliability": source.score_all(),
    }
    print(json.dumps(status, indent=2))


def cmd_verify_integrity(args):
    """Verify dataset integrity."""
    from backend.ops.versioning.dataset import DatasetVersionManager
    mgr = DatasetVersionManager()
    name = args.dataset or "jobs"
    result = mgr.verify_integrity(name)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("valid") else 1)


def main():
    parser = argparse.ArgumentParser(
        prog="python -m backend.ops.scripts",
        description="MLOps / DataOps CLI for pipeline management",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # health
    sub.add_parser("health", help="Run health checks")

    # sla
    sub.add_parser("sla", help="Show SLA dashboard")

    # backup
    p_backup = sub.add_parser("backup", help="Manage backups")
    p_backup.add_argument("action", choices=["create", "list", "config"], default="list", nargs="?")
    p_backup.add_argument("--label", default="", help="Backup label")

    # restore
    p_restore = sub.add_parser("restore", help="Restore from backup")
    p_restore.add_argument("--name", default="", help="Backup name")
    p_restore.add_argument("--latest", action="store_true", help="Use latest backup")
    p_restore.add_argument("--dry-run", action="store_true", help="Preview without restoring")

    # retention
    p_ret = sub.add_parser("retention", help="Enforce retention policies")
    p_ret.add_argument("--dry-run", action="store_true", help="Preview only")
    p_ret.add_argument("--status", action="store_true", help="Show current status")

    # deps
    p_deps = sub.add_parser("deps", help="Check dependencies")
    p_deps.add_argument("action", choices=["check", "outdated", "vulnerabilities", "lock"], default="check", nargs="?")

    # updates
    sub.add_parser("updates", help="Check component update status")

    # status
    sub.add_parser("status", help="Show pipeline status")

    # verify
    p_verify = sub.add_parser("verify", help="Verify dataset integrity")
    p_verify.add_argument("--dataset", default="jobs", help="Dataset name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "health": cmd_health,
        "sla": cmd_sla,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "retention": cmd_retention,
        "deps": cmd_deps,
        "updates": cmd_updates,
        "status": cmd_status,
        "verify": cmd_verify_integrity,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
