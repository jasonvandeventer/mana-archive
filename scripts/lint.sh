#!/bin/bash

ruff check . --fix
black .
djlint app/templates --reformat
npx prettier . --write