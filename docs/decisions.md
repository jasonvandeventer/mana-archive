# Decisions

## Why K3s
K3s was chosen because it provides a lightweight but real Kubernetes environment suitable for a homelab while still exposing the concepts needed for platform engineering work.

It makes it possible to learn and demonstrate:
- cluster operations
- workload deployment
- storage
- GitOps
- observability

without the overhead of a heavier self-managed Kubernetes distribution.

## Why Argo CD
Argo CD was chosen to move away from manual deployment habits and toward a declarative GitOps workflow.

This supports:
- versioned infrastructure and app deployment state
- repeatable changes
- reduced manual drift
- stronger portfolio and interview story

## Why App-of-Apps
The app-of-apps pattern was chosen because it creates a cleaner platform layout:
- one root application manages child applications
- individual apps remain isolated
- future platform components can be added in a structured way

## Why Mana Archive on Kubernetes
Mana Archive is both a useful personal application and a practical workload for the platform.

Running it on Kubernetes demonstrates:
- containerization
- persistent volume usage
- GitOps deployment
- real-world stateful application concerns

## Why SQLite for Now
SQLite was kept because it is simple and sufficient for the current single-user use case.

Tradeoff:
- it is easy to run
- but it increases the importance of backups and careful storage handling

## Current Tradeoffs Accepted
- local-path is simpler than distributed storage
- backup/restore is not yet implemented
- repo structure has evolved incrementally and is still being documented
