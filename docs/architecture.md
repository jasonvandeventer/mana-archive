# Architecture

## Purpose

This project serves two purposes at the same time:

1. Mana Archive is a real application for managing a personal Magic: The Gathering collection.
2. The K3s environment is a platform engineering lab used to build and demonstrate Kubernetes, GitOps, storage, and operational practices.

## High-Level Flow

Developer workflow:

1. Application code is maintained in GitHub
2. Container image is built and pushed to GHCR
3. Kubernetes manifests in this repo describe the desired application state
4. Argo CD monitors the repo and syncs changes into the cluster
5. K3s runs the application workloads

## Platform Components

- K3s cluster
- Argo CD for GitOps
- GHCR for container image hosting
- Prometheus/Grafana/Loki for observability
- local-path provisioner for current persistent storage

## Application Components

Mana Archive currently includes:

- Python application code under `app/`
- HTML templates under `app/templates/`
- CSS under `app/static/`
- SQLite database stored on a Kubernetes PVC

## Storage Model

Current storage is based on:

- `local-path` storage class
- PVC: `mana-archive-data`

This provides persistence, but not strong durability. The current model does not provide:

- distributed replication
- snapshot-based recovery
- tested backup/restore process

## Future Architecture Direction

The planned next storage evolution is:

- Longhorn installation
- recurring snapshots/backups
- external backup target
- tested restore workflow

That change will strengthen the platform story from simple persistence to stateful workload resilience.
