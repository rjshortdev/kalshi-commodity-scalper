#!/usr/bin/env bash
set -e

git add .
git commit -m "Changed readme first paragraph."
git push --set-upstream origin main --force
