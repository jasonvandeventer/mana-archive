# Argo CD Image Updater Integration

## Overview

This platform uses **Argo CD Image Updater (v1.x, CRD-based)** to automatically promote new container images from GHCR into the Kubernetes cluster via GitOps.

This replaces manual image version updates in manifests.

---

## Architecture

The deployment pipeline now follows this flow:

```
App Repo (mana-archive)
    ↓ (tagged release)
GHCR (container registry)
    ↓
Argo CD Image Updater
    ↓ (Git write-back)
Platform Repo (mana-archive-platform)
    ↓
Argo CD
    ↓
Kubernetes Cluster
```

### Key Principle

> **Git is the source of truth.**

Image Updater does NOT modify the live cluster directly.
It commits changes back to the platform repository, which Argo CD then applies.

---

## Implementation Details

### 1. Kustomize Requirement

Image Updater requires applications to be defined as:

- `Kustomize` OR
- `Helm`

Raw `Directory` applications are **not supported**.

#### Required Structure

```
k8s/apps/mana-archive/
  base/
  overlays/
    homelab/
      kustomization.yaml
```

Argo Application must point to:

```
k8s/apps/mana-archive/overlays/homelab
```

---

### 2. Argo CD Application

Location:

```
k8s/argocd/apps/mana-archive.yaml
```

Key fields:

```yaml
spec:
  source:
    repoURL: https://github.com/jasonvandeventer/mana-archive-platform.git
    targetRevision: main
    path: k8s/apps/mana-archive/overlays/homelab
```

---

### 3. ImageUpdater CRD (v1.x)

Location:

```
k8s/argocd/image-updaters/mana-archive.yaml
```

This replaces annotation-based configuration.

Example:

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: mana-archive-updater
  namespace: argocd

spec:
  namespace: argocd

  applicationRefs:
    - namePattern: mana-archive
      images:
        - alias: manaarchive
          imageName: ghcr.io/jasonvandeventer/mana-archive
          commonUpdateSettings:
            updateStrategy: semver
          manifestTargets:
            kustomize:
              name: ghcr.io/jasonvandeventer/mana-archive

  writeBackConfig:
    method: git:secret:argocd/image-updater-git-creds
    gitConfig:
      branch: main
```

---

### 4. Git Write-Back

Image Updater commits changes to:

```
k8s/apps/mana-archive/overlays/homelab/.argocd-source-mana-archive.yaml
```

This file overrides the image tag for the application.

Example:

```yaml
images:
  - name: ghcr.io/jasonvandeventer/mana-archive
    newTag: v2.1.1
```

---

### 5. Git Credentials

Kubernetes Secret:

```bash
kubectl -n argocd create secret generic image-updater-git-creds \
  --from-literal=username=<github-username> \
  --from-literal=password=<github-pat>
```

Required PAT scope:

- `repo`

---

### 6. Platform Root App (App-of-Apps)

The `platform-root` application manages all Argo applications:

```
k8s/argocd/apps/
```

Important:

> Direct `kubectl patch` or `apply` to child Applications will be overwritten.

All changes must be committed to Git.

---

## Lessons Learned

### 1. Application Source Type Matters

If Argo reports:

```
Directory
```

Image Updater will skip the app.

Must be:

```
Kustomize
```

---

### 2. App-of-Apps Ownership

Manual changes to Applications do not persist.

Always modify:

```
k8s/argocd/apps/*.yaml
```

and push to Git.

---

### 3. CRD vs Annotation Model

- v0.x → annotation-based
- v1.x → CRD-based (`ImageUpdater`)

This project uses **CRD-based configuration**.

---

### 4. GitOps Truth

Local changes do nothing.

Only this matters:

```
remote repo → Argo → cluster
```

---

## Validation

A successful update cycle includes:

1. New image tag pushed to GHCR
2. Image Updater detects new version
3. Git commit created in platform repo
4. Argo detects commit
5. Application syncs
6. Pod restarts with new image

---

## Current Status

- Image Updater installed via Helm
- Git write-back configured and verified
- Automatic updates confirmed working
- Kustomize-based application structure enforced

---

## Next Steps

- Add observability stack (Prometheus, Grafana, Loki)
- Continue application development (feature + bugfix releases)
- Standardize versioning strategy
- Optional: migrate additional apps to ImageUpdater CRDs

---
