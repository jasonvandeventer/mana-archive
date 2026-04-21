# Mana Archive

Mana Archive is a self-hosted web application for managing and organizing a physical Magic: The Gathering collection.

## Purpose

The goal of this project is to solve a real problem:

> A physical card collection is difficult to search, organize, and maintain.

Mana Archive provides:

- searchable inventory
- structured organization (drawers, sets, decks)
- import workflows
- pricing integration

---

## Architecture

This repository contains **application code only**.

Platform/infrastructure concerns are intentionally separated:

- Application repo → this repo
- Platform / Kubernetes / GitOps →  
  https://github.com/jasonvandeventer/mana-archive-platform

---

## Deployment Model

The application is deployed to a Kubernetes cluster using:

- K3s
- ArgoCD (GitOps)
- Longhorn (persistent storage)

### Key design decisions

- No infrastructure manifests in this repo
- No persistent data stored in Git
- All runtime data lives on Kubernetes persistent volumes
- Deployments are managed declaratively via ArgoCD

---

## Local Development

Run locally using Docker:

```bash
docker compose -f docker-compose.dev.yml up --build
```

App will be available at:

http://localhost:8000

---

## Data Storage

The application uses a SQLite database.

### Local

- Stored in a local `/data` directory

### Kubernetes

- Backed by a Longhorn persistent volume
- Mounted into the container at runtime

No database files are stored in this repository.

---

## Features

- Collection browsing and filtering
- Drawer-based organization
- Deck tracking
- Import workflows (CSV/manual)
- Pricing integration

---

## Future Work

- AI-assisted deck building
- Advanced collection analytics
- Improved UX and performance
- API exposure for integrations

---

## Why this project matters

This is not just an app.

It demonstrates:

- application development
- containerization
- Kubernetes deployment
- GitOps workflows
- separation of concerns between app and platform
