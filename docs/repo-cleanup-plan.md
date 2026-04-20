# Repo Cleanup Plan

## Goal
Reduce ambiguity and make the repository reflect the real deployment model.

## Confirmed Source of Truth
The active deployment paths are:
- `k8s/argocd/apps/`
- `k8s/apps/mana-archive/`
- `k8s/apps/whoami/`

These paths are referenced by Argo CD and represent the live GitOps deployment model.

## Completed Cleanup
- Archived old root-level Kubernetes manifests into `k8s/_archive/`
- Preserved active Argo CD and app manifests in their existing paths
- Stopped treating old root-level manifests as current deployment truth
- Removed runtime data from version control tracking
- Improved `.gitignore` coverage for runtime/cache artifacts

## Remaining Cleanup Questions
- Confirm the exact role of local Docker Compose in future development workflow
- Review whether helper manifests such as `mana-archive-db-helper.yaml` should remain long term
- Decide whether additional repo restructuring is worth doing later, after Argo paths can be updated safely

## Cleanup Rule Going Forward
If a file is not part of the live Argo CD deployment path or the actual application source, it must be clearly labeled, archived, or removed.

## Next Logical Follow-Up
- add architecture documentation
- add decision documentation
- add troubleshooting notes
- introduce Longhorn and backup/restore documentation later
