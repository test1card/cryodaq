#!/bin/bash
# F-KnowledgeBaseExpansion (v0.55.7.1): seed equipment manuals.
#
# Run from repo root:
#     bash scripts/download_manuals.sh
#
# Each download is best-effort. Failures log "[DEFER]" so the
# operator knows which manual still needs a manual drop, but the
# script keeps going — partial corpus > none. Re-running is safe;
# already-present files are skipped (idempotent).
#
# After this script exits, run cryodaq-rag-index OR restart the
# engine (bootstrap auto-fires on empty index) to ingest the freshly
# downloaded PDFs.

set -u

TARGET="data/knowledge/equipment_manuals"
mkdir -p "$TARGET"

download_or_skip() {
    local url="$1"
    local dest="$2"
    local label="$3"

    if [ -f "$dest" ]; then
        echo "[SKIP] $label already exists: $dest"
        return 0
    fi

    echo "[DOWNLOAD] $label..."
    if curl -L -f -s --max-time 60 -o "$dest" "$url"; then
        # curl -f returns non-zero on HTTP 4xx/5xx; the additional
        # check below catches HTML 200-OK pages вместо PDF.
        if file "$dest" | grep -q "PDF document"; then
            local size
            size=$(stat -f%z "$dest" 2>/dev/null || stat -c%s "$dest")
            echo "[OK] $label: $((size / 1024)) KB"
            return 0
        fi
        echo "[FAIL] $label: response is not a PDF (likely HTML error page)"
        rm -f "$dest"
        return 1
    fi
    echo "[FAIL] $label: curl failed"
    rm -f "$dest"
    return 1
}

# LakeShore 218S Temperature Monitor manual.
download_or_skip \
    "https://www.lakeshore.com/docs/default-source/product-downloads/manuals/218_manual.pdf" \
    "$TARGET/lakeshore_218s_manual.pdf" \
    "LakeShore 218S" \
    || echo "[DEFER] LakeShore 218S manual — operator drops manually, see /tmp/manuals-download-defer.md"

# Keithley 2600B Series Reference Manual (long, ~1500 pages).
download_or_skip \
    "https://download.tek.com/manual/2600BS-901-01.pdf" \
    "$TARGET/keithley_2600b_reference.pdf" \
    "Keithley 2600B Reference" \
    || echo "[DEFER] Keithley 2600B reference manual — operator drops manually"

# Keithley 2600B Series User's Manual (short).
download_or_skip \
    "https://download.tek.com/manual/2600BS-900-01.pdf" \
    "$TARGET/keithley_2600b_users.pdf" \
    "Keithley 2600B Users" \
    || echo "[DEFER] Keithley 2600B users manual — operator drops manually"

echo
echo "=== Manual download summary ==="
ls -lh "$TARGET"/*.pdf 2>/dev/null || echo "No manuals downloaded"
echo
echo "Next step: run cryodaq-rag-index OR restart engine to ingest."
