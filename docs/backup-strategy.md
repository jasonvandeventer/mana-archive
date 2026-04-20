# Backup Strategy

## Goal

Protect Mana Archive application data from accidental loss, storage failure, bad deployment changes, or failed migration work.

## Scope

This strategy currently applies to the persistent data used by Mana Archive.

## What is being protected

- Application: Mana Archive
- PersistentVolumeClaim: `mana-archive-data`
- Database type: SQLite
- Deployment namespace: `mana-archive`

## Why this matters

Mana Archive is now running with real collection data. The platform is only credible if that data can be recovered after a failure.

## Current State

- Kubernetes storage class: `local-path`
- Persistent data exists and is in use
- No distributed storage layer is installed
- No recurring snapshot schedule exists
- No external backup target is configured
- No tested restore procedure exists

## Current Risk

The current setup provides persistence, but not strong durability. A storage problem, node issue, or operator mistake could result in data loss.

## Planned Direction

The storage and backup model will be improved in the following order:

1. Install Longhorn on the K3s cluster
2. Move Mana Archive persistent storage to Longhorn
3. Configure an external backup target
4. Create recurring snapshot and backup jobs
5. Test restore
6. Document the restore procedure

## Proposed Backup Target

- Unraid-hosted NFS share dedicated to Longhorn backups

## Proposed Backup Policy

- Snapshot frequency: every 6 hours
- Backup frequency: daily
- Retention: to be defined during Longhorn setup based on available storage and observed backup size

## Restore Objective

Restore Mana Archive data from backup and return the application to a working state with collection data intact and validated.

## Success Criteria

This strategy will be considered implemented only when all of the following are true:

- Longhorn is installed and healthy
- Mana Archive uses Longhorn-backed persistent storage
- Backup target is configured and reachable
- Recurring backups are running successfully
- A restore test has been completed successfully
- The restore process is documented in `docs/restore-runbook.md`
