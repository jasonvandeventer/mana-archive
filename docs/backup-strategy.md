# Backup Strategy

## Purpose

Define how Mana Archive application data is protected and recovered in the K3s platform.

---

## Scope

Applies to persistent data used by Mana Archive.

---

## Protected Resources

- Application: Mana Archive
- Namespace: `mana-archive`
- PersistentVolumeClaim: `mana-archive-data`
- Database: SQLite (file-based)

---

## Storage Architecture

- StorageClass: `longhorn` (default)
- Storage Backend: Longhorn distributed block storage
- Replication: Longhorn volume replicas across nodes

---

## Backup Architecture

- Backup Target: Unraid NFS share
  - Path: `/mnt/user/backups/longhorn`
- Protocol: NFSv4

---

## Backup Policy

- Snapshots:
  - Frequency: every 1 hour
  - Retention: 24

- Backups:
  - Frequency: every 6 hours
  - Retention: 10

- Managed via Longhorn recurring jobs

---

## Guarantees

The system provides:

- Persistent storage across pod restarts
- Resilience against node failure (via Longhorn replication)
- Recovery from cluster-level failure (via NFS backups)
- Verified ability to restore data into a new volume and reattach to workloads

---

## Validation Status

The following has been tested and confirmed:

1. Data written to Longhorn-backed volume
2. Snapshot created from live data
3. Backup stored on external NFS target
4. Backup restored into new Longhorn volume
5. Restored volume mounted in Kubernetes pod
6. Data integrity verified (file + timestamp match)

Detailed validation is documented in:
~/lab/platform-docs/longhorn/backup-validation.md

---

## Restore Process

High-level recovery flow:

1. Identify latest valid backup
2. Restore backup into new Longhorn volume
3. Create PV pointing to restored volume
4. Bind PVC to restored volume
5. Reattach application pod to restored PVC
6. Validate application functionality and data integrity

A detailed restore runbook will be created separately.

---

## Risks / Limitations

- Backup frequency introduces up to 6 hours of potential data loss
- NFS backup target is a single location (no offsite redundancy)
- Restore process is currently manual
- SQLite database may not be optimal for concurrent or large-scale workloads

---

## Future Improvements

- Add offsite backup (S3-compatible storage)
- Automate restore workflow
- Evaluate migration from SQLite to managed database (PostgreSQL)
