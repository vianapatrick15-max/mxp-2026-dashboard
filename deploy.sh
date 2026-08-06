#!/bin/bash
# Rebuild + publica no Cloudflare Pages (https://mxp-2026-dashboard.pages.dev/)
set -e
cd "$(dirname "$0")"
/usr/bin/python3 build.py
mkdir -p _site && cp index.html _site/index.html
export CLOUDFLARE_API_TOKEN=$(grep CLOUDFLARE_API_TOKEN ~/.claude/secrets/cloudflare.env | cut -d= -f2- | tr -d "\"' \n")
export CLOUDFLARE_ACCOUNT_ID=$(tr -d '\n' < ~/.claude/secrets/cloudflare-account.txt)
wrangler pages deploy _site --project-name mxp-2026-dashboard --branch main --commit-dirty=true
