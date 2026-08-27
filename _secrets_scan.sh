#!/usr/bin/env bash
# Secrets scan across ALL commits on ALL branches (read-only). Exits 0 if clean.
set -u
cd /Users/mangeshrahangdale/Downloads/OneClick-LCA-Apparel

echo "Scanning every blob in history for credential leak patterns..."

# Collect every commit object reachable from every ref.
commits=$(git rev-list --all)

# Known high-signal credential patterns (AWS, GitHub PAT, Slack, Google API,
# OpenAI-style sk-, private key headers, generic password= assignments).
patterns='(AKIA[0-9A-Z]{16})|(ghp_[A-Za-z0-9]{36})|(gho_[A-Za-z0-9]{36})|(github_pat_[A-Za-z0-9_]{82})|(xox[baprs]-[A-Za-z0-9-]{10,})|(AIza[0-9A-Za-z_-]{35})|(^sk-[A-Za-z0-9]{20,})|(-----BEGIN (RSA|EC|OPENSSH|DSA|PRIVATE) PRIVATE KEY-----)'

found=0
for sha in $commits; do
  hits=$(git grep -hEI "$patterns" "$sha" 2>/dev/null)
  if [ -n "$hits" ]; then
    echo "LEAK in $sha:"
    echo "$hits" | head -5
    found=1
  fi
done

# Also scan working tree for plaintext password assignments that aren't a
# template/example, plus connection strings with embedded credentials.
echo "--- scanning working tree for password=/password: leaks ---"
tree_hits=$(git grep -nIE '(password|passwd|pwd|secret|api_key|apikey|access_token)["'\'' ]*[:=]["'\'' ]*[A-Za-z0-9/_+.-]{8,}' -- . ':(exclude)*.md' ':(exclude)*.csv' 2>/dev/null | head -20)
if [ -n "$tree_hits" ]; then
  echo "POSSIBLE WORKING-TREE ASSIGNMENTS (review each):"
  echo "$tree_hits"
  found=1
fi

if [ "$found" = 0 ]; then
  echo "SECRETS SCAN: CLEAN — no known credential patterns in history or working tree."
  exit 0
else
  echo "SECRETS SCAN: FLAGGED items above — review before pushing."
  exit 1
fi
