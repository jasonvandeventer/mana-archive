# Problems and Fixes

## Purpose
This document captures meaningful engineering problems encountered during the buildout of the platform and application.

It exists for three reasons:
1. to preserve troubleshooting knowledge
2. to improve future execution
3. to provide concrete project stories for interviews and portfolio writeups

## CIDR Conflict Risk
### Problem
The cluster networking needed to avoid conflict with the existing home LAN addressing.

### Why It Mattered
Incorrect overlap between cluster/service networking and home network ranges could create routing confusion and future instability.

### Fix
The cluster CIDR and service CIDR were reviewed and corrected so the Kubernetes networking model would not conflict with the home LAN.

### Result
The cluster networking became more intentional and safer to build on.

## Pod Rebuild / Replacement Confusion
### Problem
Stopping a pod did not behave like stopping a normal standalone container because Kubernetes immediately recreated it.

### Why It Mattered
This highlighted the difference between container management and declarative orchestration.

### Fix
The issue was resolved by understanding the controller behavior and modifying the correct Kubernetes resource rather than fighting the pod directly.

### Result
This reinforced the operational model of Kubernetes and reduced confusion around workload lifecycle.

## Data Migration to K3s
### Problem
Application data needed to be moved from the earlier environment into the Kubernetes-hosted version without losing the working dataset.

### Why It Mattered
The application only has value if the collection data survives the platform transition.

### Fix
The data was successfully migrated into the Kubernetes-backed application storage and validated in the running application.

### Result
Mana Archive became live on the K3s platform with usable real data.

## Argo CD Sync / Manifest Troubleshooting
### Problem
Argo CD initially encountered sync and manifest-generation issues during setup.

### Why It Mattered
GitOps only adds value if the cluster can reliably reconcile from the repo.

### Fix
The Argo CD configuration and manifest structure were corrected until the applications became Healthy and Synced.

### Result
The project now uses a functioning GitOps deployment flow for the active workloads.

## Repo Ambiguity
### Problem
The repository accumulated older Kubernetes manifests alongside the live Argo-managed structure, making the active source of truth unclear.

### Why It Mattered
Confusing repo structure makes the system harder to understand, harder to maintain, and harder to explain to interviewers.

### Fix
Legacy root-level manifests were archived and the active deployment paths were identified and documented.

### Result
The repo now better reflects the real deployment model.
