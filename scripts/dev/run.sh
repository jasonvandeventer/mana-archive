#!/usr/bin/env bash
set -eou pipefail

cd "$(dirname "$0")/../.."

export PYTHONPATH=.
export DATA_DIR=dev-data

exec .venv/bin/uvicorn app.main:app --reload
