# Current State

## Overview

Mana Archive is a Python web application deployed to a 4-node K3s cluster using Argo CD.

This repository now contains both:

- the application source code for Mana Archive
- the Kubernetes and Argo CD manifests used to deploy it

## Cluster

- Kubernetes distribution: K3s
- Node count: 4
- OS: Rocky Linux 9.7
- Current default storage class: `local-path`
- Longhorn: not installed
- Backups: not implemented

## GitOps Structure

The live GitOps deployment path is:

- `k8s/argocd/apps/`
- `k8s/apps/mana-archive/`
- `k8s/apps/whoami/`

Argo CD applications confirmed:

- `platform-root`
- `mana-archive`
- `whoami`

## Mana Archive Deployment

Argo CD deploys Mana Archive from:

- `k8s/apps/mana-archive`

Current deployed resources:

- Namespace: `mana-archive`
- PVC: `mana-archive-data`
- Pod: `mana-archive-db-helper`
- Service: `mana-archive`
- Deployment: `mana-archive`

Current image:

- `ghcr.io/jasonvandeventer/mana-archive:v2.0.17`

## Local / Non-Cluster Artifacts

These exist for development or historical work and are not the live cluster source of truth:

- `docker-compose.yml` or local dev compose flow
- local `data/` directory contents
- archived Kubernetes manifests under `k8s/_archive/`

## Known Gaps

- No Kubernetes-native distributed storage
- No tested backup/restore workflow
- No storage redundancy
- Documentation is still being established
