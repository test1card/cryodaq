#!/usr/bin/env bash
#
# Rebuild the RAG literature corpus from its manifests.
#
# The PDFs themselves are deliberately not in git (see .gitignore): ~250 MB of
# third-party documents, much of it vendor copyright that this lab may hold and
# index but may not redistribute. What IS in git is the provenance — one TSV per
# topic under docs/literature/, each line "filename<TAB>url".
#
# Rerunning is cheap and safe: a file that is already present and already starts
# with the %PDF magic number is skipped, so an interrupted run resumes.
#
# Usage:  tools/fetch_literature.sh [topic ...]      (default: every topic)
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_DIR="$ROOT/docs/literature"
DEST_ROOT="$ROOT/data/knowledge/literature"
UA='Mozilla/5.0 (X11; Linux x86_64) cryodaq-literature-fetch/1.0'

topics=("$@")
if [ ${#topics[@]} -eq 0 ]; then
  topics=()
  for f in "$MANIFEST_DIR"/*.tsv; do
    [ -e "$f" ] || continue
    topics+=("$(basename "$f" .tsv)")
  done
fi

ok=0; skipped=0; failed=0
for topic in "${topics[@]}"; do
  manifest="$MANIFEST_DIR/$topic.tsv"
  if [ ! -f "$manifest" ]; then
    echo "no manifest for topic '$topic' ($manifest)" >&2
    failed=$((failed + 1))
    continue
  fi
  mkdir -p "$DEST_ROOT/$topic"
  while IFS=$'\t' read -r name url; do
    [ -z "${name:-}" ] && continue
    case "$name" in \#*) continue ;; esac
    out="$DEST_ROOT/$topic/$name"

    # Already fetched and really a PDF — leave it alone.
    if [ -s "$out" ] && head -c4 "$out" | grep -q '%PDF'; then
      skipped=$((skipped + 1))
      continue
    fi

    code=$(curl -sSL --max-time 300 --retry 2 --retry-delay 3 -A "$UA" \
             -w '%{http_code}' -o "$out.part" "$url" 2>/dev/null)

    if { [ "$code" = "200" ] || [ "$code" = "206" ]; } \
       && head -c4 "$out.part" | grep -q '%PDF'; then
      mv "$out.part" "$out"
      printf 'OK    %s/%s  %s\n' "$topic" "$name" "$(du -h "$out" | cut -f1)"
      ok=$((ok + 1))
    else
      # A publisher that bot-walls scripted clients answers 200 with HTML, which
      # is why the magic number is checked and not just the status code.
      printf 'FAIL  %s/%s  (http %s, %s)  %s\n' \
        "$topic" "$name" "$code" \
        "$(file -b --mime-type "$out.part" 2>/dev/null || echo none)" "$url"
      rm -f "$out.part"
      failed=$((failed + 1))
    fi
  done < "$manifest"
done

printf '\nfetched %d, already present %d, failed %d\n' "$ok" "$skipped" "$failed"
[ "$failed" -eq 0 ]
