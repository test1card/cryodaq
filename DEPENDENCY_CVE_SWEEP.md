# CryoDAQ Dependency CVE Sweep

**Date:** 2026-04-09  
**Branch:** `master`  
**Files reviewed:** `requirements-lock.txt`, `pyproject.toml`  
**Dependencies checked:** 71 total

## Summary

- Exact pinned runtime/dev/web dependencies in `requirements-lock.txt`: 70
- Unpinned build backend dependencies in `pyproject.toml`: 1 (`hatchling`)
- Confirmed vulnerable pinned dependencies: 0
- Historical CVEs reviewed in detail: 8
- External lookups performed: at least 230
  - 70 exact-version PyPI JSON lookups
  - 71 NVD package/CVE queries
  - 71 GitHub Advisories searches
  - targeted vendor/release-note/package-manifest fetches on top

## Findings

### 1. [HIGH] `requirements-lock.txt` does not use hash verification

`requirements-lock.txt` contains exact version pins, but no `--hash=sha256:...` entries. Local check:

```text
$ rg -n -- '--hash=' requirements-lock.txt
# no output
```

This means the lockfile prevents resolver drift, but it does not force `pip` to verify artifact hashes. For a safety-critical PyInstaller deployment, that leaves room for malicious or corrupted artifact substitution on an index, mirror, or cache layer. `pip-compile` supports hash-locked output, so this is a hardening gap in the current build chain rather than a tooling limitation.

### 2. [MEDIUM] Build backend `hatchling` is unpinned

`pyproject.toml` currently declares:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

That means source builds are not reproducible at the build-backend layer. Even if the runtime lockfile is pinned, a future `hatchling` regression or compromised release can alter wheel/sdist build behavior. For a deployment pipeline already relying on `requirements-lock.txt`, leaving the build backend floating is avoidable risk.

## Re-verification of high-risk packages

### aiohttp 3.13.5

Pinned version: `3.13.5`  
Exact-version PyPI advisory feed: `0` vulnerabilities.

Direct NVD re-checks:

- `CVE-2021-21330`: NVD says aiohttp had an open redirect issue “before version 3.7.4” and “This security problem has been fixed in 3.7.4.”
- `CVE-2024-23334`: NVD says “Version 3.9.2 fixes this issue.”
- `CVE-2024-30251`: NVD says “This issue has been addressed in version 3.9.4.”
- `CVE-2025-69228`: NVD says “Versions 3.13.2 and below” are affected and it “is fixed in version 3.13.3.”

Verdict: `aiohttp==3.13.5` is **SAFE** against the specific CVEs above.

URLs consulted:

- `https://pypi.org/pypi/aiohttp/3.13.5/json`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=aiohttp&resultsPerPage=5`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2021-21330`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-23334`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-30251`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2025-69228`
- `https://github.com/advisories?query=aiohttp`

### PyInstaller 6.19.0

Pinned version: `6.19.0`  
Exact-version PyPI advisory feed: `0` vulnerabilities.

Direct NVD re-checks:

- `CVE-2019-16784`: NVD says “In PyInstaller before version 3.6 ... a local privilege escalation vulnerability is present.”
- `CVE-2023-49797`: NVD describes a privileged-process deletion issue in older PyInstaller bundles.
- `CVE-2025-59042`: NVD says applications “built with PyInstaller < 6.0.0” may be tricked into executing arbitrary Python code.

Verdict: `pyinstaller==6.19.0` is **SAFE** against the PyInstaller CVEs re-verified in this pass, including `CVE-2025-59042`.

URLs consulted:

- `https://pypi.org/pypi/pyinstaller/6.19.0/json`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyinstaller&resultsPerPage=5`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2019-16784`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2023-49797`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2025-59042`
- `https://github.com/advisories?query=pyinstaller`
- `https://github.com/advisories/GHSA-p2xp-xx3r-mffc`

### PyYAML 6.0.3

Pinned version: `6.0.3`  
Exact-version PyPI advisory feed: `0` vulnerabilities.

Historical CVE re-check:

- `CVE-2020-14343`: NVD says the arbitrary code execution issue exists in PyYAML “versions before 5.4”.

Verdict: `pyyaml==6.0.3` is **SAFE** against this historical RCE class by version range. This does not remove the separate application-level requirement to keep using `safe_load`, but the pinned package version is not in the affected range.

URLs consulted:

- `https://pypi.org/pypi/pyyaml/6.0.3/json`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyyaml&resultsPerPage=5`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2020-14343`
- `https://github.com/advisories?query=pyyaml`

### Pillow 12.2.0 and lxml 6.0.2

Pinned versions:

- `pillow==12.2.0`
- `lxml==6.0.2`

Both exact-version PyPI advisory feeds returned `0` vulnerabilities. Both package names have historical security noise in NVD/GHSA searches, but this sweep did **not** identify a package-specific advisory whose affected range includes the pinned versions above.

Verdict:

- `pillow==12.2.0`: **SAFE** in this sweep
- `lxml==6.0.2`: **SAFE** in this sweep

URLs consulted:

- `https://pypi.org/pypi/pillow/12.2.0/json`
- `https://pypi.org/pypi/lxml/6.0.2/json`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pillow&resultsPerPage=5`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=lxml&resultsPerPage=5`
- `https://github.com/advisories?query=pillow`
- `https://github.com/advisories?query=lxml`

### pyqtgraph 0.13.7

Pinned version: `0.13.7`

Result: no CVE was found for this exact pin in the PyPI exact-version vulnerability feed, NVD keyword search returned `0`, and GitHub advisories search did not surface a pyqtgraph advisory. I did find issue-tracker noise around runtime bugs and PySide interactions, but not a security advisory affecting `0.13.7`.

Verdict: `pyqtgraph==0.13.7` is **SAFE** from a CVE perspective in this sweep.

URLs consulted:

- `https://pypi.org/pypi/pyqtgraph/0.13.7/json`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyqtgraph&resultsPerPage=5`
- `https://github.com/advisories?query=pyqtgraph`
- `https://github.com/pyqtgraph/pyqtgraph/releases`
- `https://github.com/pyqtgraph/pyqtgraph/issues`

### PySide6 6.11.0 release notes

Pinned version: `6.11.0`

Security result: no PyPI exact-version advisory, NVD package search `0`, GitHub advisories search did not surface a PySide6 advisory.  
Behavior/release-note review:

- Official Qt for Python 6.11.0 release notes say: “Signal emission has been sped up by code optimizations.”
- The same release-note stream also documents in 6.10.3: “A crash when connecting a slot with result to a signal has been fixed.”

I did **not** find an official 6.11.0 note specifically calling out `QThread` or `QTimer` regressions. For CryoDAQ, the signal/slot delivery change is relevant operationally because the GUI and engine rely on frequent signal delivery, but it is not a CVE.

URLs consulted:

- `https://pypi.org/pypi/pyside6/6.11.0/json`
- `https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyside6&resultsPerPage=5`
- `https://github.com/advisories?query=pyside6`
- `https://doc.qt.io/qtforpython-6/release_notes/pyside6_release_notes.html`
- `https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-supported-platforms.html`

### SQLite on Ubuntu 22.04 target

This is not a Python dependency pin in `requirements-lock.txt`, but it matters for deployment risk.

- Ubuntu Jammy package metadata shows `libsqlite3-0` at `3.37.2-2ubuntu0.5`.
- SQLite’s official WAL documentation still states that “WAL provides more concurrency as readers do not block writers” and also that “All processes using a database must be on the same host computer”.

This confirms the earlier deployment concern: CryoDAQ’s SQLite behavior on the target Ubuntu base will be governed by an older distro SQLite, not whatever newer upstream SQLite release notes the developer might have in mind.

URLs consulted:

- `https://packages.ubuntu.com/jammy/libsqlite3-0`
- `https://sqlite.org/wal.html`

## Comprehensive dependency table

Interpretation notes:

- “PyPI exact-version” is the strongest exact-pin check in this sweep.
- NVD keyword totals are package-name searches, so common names such as `build`, `click`, `wheel`, `six`, `packaging` are noisy.
- A package can have many historical NVD hits and still be safe at the pinned version if the affected range is below the pin.

| Package | Pinned version | CVE list / range verification | Verdict | URLs consulted |
|---|---:|---|---|---|
| aiohappyeyeballs | 2.6.1 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/aiohappyeyeballs/2.6.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=aiohappyeyeballs&resultsPerPage=5`<br>`https://github.com/advisories?query=aiohappyeyeballs` |
| aiohttp | 3.13.5 | Exact-version PyPI advisory count=`0`. Re-verified historical CVEs: `CVE-2021-21330` (<3.7.4), `CVE-2024-23334` (fixed 3.9.2), `CVE-2024-30251` (fixed 3.9.4), `CVE-2025-69228` (affected 3.13.2 and below; fixed 3.13.3). Pinned version is above all fixed versions. | SAFE | `https://pypi.org/pypi/aiohttp/3.13.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=aiohttp&resultsPerPage=5`<br>`https://github.com/advisories?query=aiohttp` |
| aiosignal | 1.4.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/aiosignal/1.4.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=aiosignal&resultsPerPage=5`<br>`https://github.com/advisories?query=aiosignal` |
| altgraph | 0.17.5 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/altgraph/0.17.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=altgraph&resultsPerPage=5`<br>`https://github.com/advisories?query=altgraph` |
| annotated-doc | 0.0.4 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/annotated-doc/0.0.4/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=annotated-doc&resultsPerPage=5`<br>`https://github.com/advisories?query=annotated-doc` |
| annotated-types | 0.7.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search returned no actionable advisory affecting the pin. | SAFE | `https://pypi.org/pypi/annotated-types/0.7.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=annotated-types&resultsPerPage=5`<br>`https://github.com/advisories?query=annotated-types` |
| anyio | 4.13.0 | No exact-version PyPI advisory. NVD keyword search total=`1`; GH advisories search returned no advisory affecting `4.13.0`. | SAFE | `https://pypi.org/pypi/anyio/4.13.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=anyio&resultsPerPage=5`<br>`https://github.com/advisories?query=anyio` |
| attrs | 26.1.0 | No exact-version PyPI advisory. NVD keyword search total=`15`; GH advisories search returned no advisory affecting `26.1.0`. | SAFE | `https://pypi.org/pypi/attrs/26.1.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=attrs&resultsPerPage=5`<br>`https://github.com/advisories?query=attrs` |
| build | 1.4.2 | No exact-version PyPI advisory. NVD keyword search total=`5486` is pure keyword noise for a generic term; no build-package advisory affecting `1.4.2` was confirmed. | SAFE | `https://pypi.org/pypi/build/1.4.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=build&resultsPerPage=5`<br>`https://github.com/advisories?query=build` |
| click | 8.3.2 | No exact-version PyPI advisory. NVD keyword search total=`3300` is keyword noise for a generic term; no click advisory affecting `8.3.2` was confirmed. | SAFE | `https://pypi.org/pypi/click/8.3.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=click&resultsPerPage=5`<br>`https://github.com/advisories?query=click` |
| contourpy | 1.3.3 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/contourpy/1.3.3/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=contourpy&resultsPerPage=5`<br>`https://github.com/advisories?query=contourpy` |
| coverage[toml] | 7.13.5 | No exact-version PyPI advisory. NVD keyword search total=`45`; no advisory affecting exact pin was confirmed. | SAFE | `https://pypi.org/pypi/coverage/7.13.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=coverage&resultsPerPage=5`<br>`https://github.com/advisories?query=coverage` |
| cycler | 0.12.1 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting exact pin was confirmed. | SAFE | `https://pypi.org/pypi/cycler/0.12.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=cycler&resultsPerPage=5`<br>`https://github.com/advisories?query=cycler` |
| et-xmlfile | 2.0.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/et-xmlfile/2.0.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=et-xmlfile&resultsPerPage=5`<br>`https://github.com/advisories?query=et-xmlfile` |
| fastapi | 0.135.3 | No exact-version PyPI advisory. NVD keyword search total=`29`; no package-specific advisory affecting `0.135.3` was confirmed. | SAFE | `https://pypi.org/pypi/fastapi/0.135.3/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=fastapi&resultsPerPage=5`<br>`https://github.com/advisories?query=fastapi` |
| fonttools | 4.62.1 | No exact-version PyPI advisory. NVD keyword search total=`2`; no advisory affecting `4.62.1` was confirmed. | SAFE | `https://pypi.org/pypi/fonttools/4.62.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=fonttools&resultsPerPage=5`<br>`https://github.com/advisories?query=fonttools` |
| frozenlist | 1.8.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/frozenlist/1.8.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=frozenlist&resultsPerPage=5`<br>`https://github.com/advisories?query=frozenlist` |
| h11 | 0.16.0 | No exact-version PyPI advisory. NVD keyword search total=`3`; no advisory affecting `0.16.0` was confirmed. | SAFE | `https://pypi.org/pypi/h11/0.16.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=h11&resultsPerPage=5`<br>`https://github.com/advisories?query=h11` |
| h5py | 3.16.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; no advisory affecting `3.16.0` was confirmed. | SAFE | `https://pypi.org/pypi/h5py/3.16.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=h5py&resultsPerPage=5`<br>`https://github.com/advisories?query=h5py` |
| httptools | 0.7.1 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/httptools/0.7.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=httptools&resultsPerPage=5`<br>`https://github.com/advisories?query=httptools` |
| idna | 3.11 | No exact-version PyPI advisory. NVD keyword search total=`6`; no advisory affecting `3.11` was confirmed. | SAFE | `https://pypi.org/pypi/idna/3.11/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=idna&resultsPerPage=5`<br>`https://github.com/advisories?query=idna` |
| iniconfig | 2.3.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/iniconfig/2.3.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=iniconfig&resultsPerPage=5`<br>`https://github.com/advisories?query=iniconfig` |
| kiwisolver | 1.5.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/kiwisolver/1.5.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=kiwisolver&resultsPerPage=5`<br>`https://github.com/advisories?query=kiwisolver` |
| lxml | 6.0.2 | Exact-version PyPI advisory count=`0`. NVD keyword search total=`17`; GitHub advisories search returned package hits but none whose affected range included `6.0.2` in this sweep. | SAFE | `https://pypi.org/pypi/lxml/6.0.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=lxml&resultsPerPage=5`<br>`https://github.com/advisories?query=lxml` |
| macholib | 1.16.4 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/macholib/1.16.4/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=macholib&resultsPerPage=5`<br>`https://github.com/advisories?query=macholib` |
| matplotlib | 3.10.8 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting `3.10.8` was confirmed. | SAFE | `https://pypi.org/pypi/matplotlib/3.10.8/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=matplotlib&resultsPerPage=5`<br>`https://github.com/advisories?query=matplotlib` |
| msgpack | 1.1.2 | No exact-version PyPI advisory. NVD keyword search total=`9`; no advisory affecting `1.1.2` was confirmed. | SAFE | `https://pypi.org/pypi/msgpack/1.1.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=msgpack&resultsPerPage=5`<br>`https://github.com/advisories?query=msgpack` |
| multidict | 6.7.1 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/multidict/6.7.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=multidict&resultsPerPage=5`<br>`https://github.com/advisories?query=multidict` |
| numpy | 2.4.4 | No exact-version PyPI advisory. NVD keyword search total=`15`; no advisory affecting `2.4.4` was confirmed. | SAFE | `https://pypi.org/pypi/numpy/2.4.4/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=numpy&resultsPerPage=5`<br>`https://github.com/advisories?query=numpy` |
| openpyxl | 3.1.5 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting `3.1.5` was confirmed. | SAFE | `https://pypi.org/pypi/openpyxl/3.1.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=openpyxl&resultsPerPage=5`<br>`https://github.com/advisories?query=openpyxl` |
| packaging | 26.0 | No exact-version PyPI advisory. NVD keyword search total=`63`; keyword-heavy results only, no advisory affecting exact pin was confirmed. | SAFE | `https://pypi.org/pypi/packaging/26.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=packaging&resultsPerPage=5`<br>`https://github.com/advisories?query=packaging` |
| pillow | 12.2.0 | Exact-version PyPI advisory count=`0`. NVD keyword search total=`57`; GitHub advisories search returned package hits but none whose affected range included `12.2.0` in this sweep. | SAFE | `https://pypi.org/pypi/pillow/12.2.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pillow&resultsPerPage=5`<br>`https://github.com/advisories?query=pillow` |
| pip-tools | 7.5.3 | No exact-version PyPI advisory. NVD keyword search total=`0`; no advisory affecting `7.5.3` was confirmed. | SAFE | `https://pypi.org/pypi/pip-tools/7.5.3/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pip-tools&resultsPerPage=5`<br>`https://github.com/advisories?query=pip-tools` |
| pluggy | 1.6.0 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting `1.6.0` was confirmed. | SAFE | `https://pypi.org/pypi/pluggy/1.6.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pluggy&resultsPerPage=5`<br>`https://github.com/advisories?query=pluggy` |
| propcache | 0.4.1 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/propcache/0.4.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=propcache&resultsPerPage=5`<br>`https://github.com/advisories?query=propcache` |
| pydantic | 2.12.5 | No exact-version PyPI advisory. NVD keyword search total=`8`; no advisory affecting `2.12.5` was confirmed. | SAFE | `https://pypi.org/pypi/pydantic/2.12.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pydantic&resultsPerPage=5`<br>`https://github.com/advisories?query=pydantic` |
| pydantic-core | 2.41.5 | No exact-version PyPI advisory. NVD keyword search total=`0`; no advisory affecting `2.41.5` was confirmed. | SAFE | `https://pypi.org/pypi/pydantic-core/2.41.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pydantic-core&resultsPerPage=5`<br>`https://github.com/advisories?query=pydantic-core` |
| pygments | 2.20.0 | No exact-version PyPI advisory. NVD keyword search total=`6`; no advisory affecting `2.20.0` was confirmed. | SAFE | `https://pypi.org/pypi/pygments/2.20.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pygments&resultsPerPage=5`<br>`https://github.com/advisories?query=pygments` |
| pyinstaller | 6.19.0 | Exact-version PyPI advisory count=`0`. Re-verified historical CVEs: `CVE-2019-16784` (<3.6), `CVE-2023-49797` (older privileged-temp handling issue), `CVE-2025-59042` (<6.0.0). Pinned version is outside affected ranges. | SAFE | `https://pypi.org/pypi/pyinstaller/6.19.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyinstaller&resultsPerPage=5`<br>`https://github.com/advisories?query=pyinstaller` |
| pyinstaller-hooks-contrib | 2026.4 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyinstaller-hooks-contrib/2026.4/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyinstaller-hooks-contrib&resultsPerPage=5`<br>`https://github.com/advisories?query=pyinstaller-hooks-contrib` |
| pyparsing | 3.3.2 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting `3.3.2` was confirmed. | SAFE | `https://pypi.org/pypi/pyparsing/3.3.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyparsing&resultsPerPage=5`<br>`https://github.com/advisories?query=pyparsing` |
| pyproject-hooks | 1.2.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyproject-hooks/1.2.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyproject-hooks&resultsPerPage=5`<br>`https://github.com/advisories?query=pyproject-hooks` |
| pyqtgraph | 0.13.7 | Exact-version PyPI advisory count=`0`. NVD keyword search total=`0`; GH advisories search=`0`. Known issue tracker noise exists, but no CVE affecting `0.13.7` was confirmed. | SAFE | `https://pypi.org/pypi/pyqtgraph/0.13.7/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyqtgraph&resultsPerPage=5`<br>`https://github.com/advisories?query=pyqtgraph` |
| pyserial | 3.5 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyserial/3.5/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyserial&resultsPerPage=5`<br>`https://github.com/advisories?query=pyserial` |
| pyserial-asyncio | 0.6 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyserial-asyncio/0.6/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyserial-asyncio&resultsPerPage=5`<br>`https://github.com/advisories?query=pyserial-asyncio` |
| pyside6 | 6.11.0 | Exact-version PyPI advisory count=`0`. NVD keyword search total=`0`; GH advisories search=`0`. Official release notes reviewed for behavior changes. | SAFE | `https://pypi.org/pypi/pyside6/6.11.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyside6&resultsPerPage=5`<br>`https://github.com/advisories?query=pyside6` |
| pyside6-addons | 6.11.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyside6-addons/6.11.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyside6-addons&resultsPerPage=5`<br>`https://github.com/advisories?query=pyside6-addons` |
| pyside6-essentials | 6.11.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyside6-essentials/6.11.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyside6-essentials&resultsPerPage=5`<br>`https://github.com/advisories?query=pyside6-essentials` |
| pytest | 9.0.3 | No exact-version PyPI advisory. NVD keyword search total=`2`; no advisory affecting `9.0.3` was confirmed. | SAFE | `https://pypi.org/pypi/pytest/9.0.3/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pytest&resultsPerPage=5`<br>`https://github.com/advisories?query=pytest` |
| pytest-asyncio | 1.3.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pytest-asyncio/1.3.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pytest-asyncio&resultsPerPage=5`<br>`https://github.com/advisories?query=pytest-asyncio` |
| pytest-cov | 7.1.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pytest-cov/7.1.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pytest-cov&resultsPerPage=5`<br>`https://github.com/advisories?query=pytest-cov` |
| python-dateutil | 2.9.0.post0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/python-dateutil/2.9.0.post0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=python-dateutil&resultsPerPage=5`<br>`https://github.com/advisories?query=python-dateutil` |
| python-docx | 1.2.0 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting `1.2.0` was confirmed. | SAFE | `https://pypi.org/pypi/python-docx/1.2.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=python-docx&resultsPerPage=5`<br>`https://github.com/advisories?query=python-docx` |
| python-dotenv | 1.2.2 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/python-dotenv/1.2.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=python-dotenv&resultsPerPage=5`<br>`https://github.com/advisories?query=python-dotenv` |
| pyvisa | 1.16.2 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/pyvisa/1.16.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyvisa&resultsPerPage=5`<br>`https://github.com/advisories?query=pyvisa` |
| pyyaml | 6.0.3 | Exact-version PyPI advisory count=`0`. Historical `CVE-2020-14343` affects versions before `5.4`; pinned version is above the fixed range. | SAFE | `https://pypi.org/pypi/pyyaml/6.0.3/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyyaml&resultsPerPage=5`<br>`https://github.com/advisories?query=pyyaml` |
| pyzmq | 26.4.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search returned no advisory affecting `26.4.0`. | SAFE | `https://pypi.org/pypi/pyzmq/26.4.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=pyzmq&resultsPerPage=5`<br>`https://github.com/advisories?query=pyzmq` |
| ruff | 0.15.9 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/ruff/0.15.9/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=ruff&resultsPerPage=5`<br>`https://github.com/advisories?query=ruff` |
| scipy | 1.17.1 | No exact-version PyPI advisory. NVD keyword search total=`3`; no advisory affecting `1.17.1` was confirmed. | SAFE | `https://pypi.org/pypi/scipy/1.17.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=scipy&resultsPerPage=5`<br>`https://github.com/advisories?query=scipy` |
| shiboken6 | 6.11.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/shiboken6/6.11.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=shiboken6&resultsPerPage=5`<br>`https://github.com/advisories?query=shiboken6` |
| six | 1.17.0 | No exact-version PyPI advisory. NVD keyword search total=`94` is heavily keyword-noisy; no six-package advisory affecting `1.17.0` was confirmed. | SAFE | `https://pypi.org/pypi/six/1.17.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=six&resultsPerPage=5`<br>`https://github.com/advisories?query=six` |
| starlette | 1.0.0 | Exact-version PyPI advisory count=`0`. Historical package-level NVD/GHSA hits exist, but none with an affected range including `1.0.0` were confirmed in this sweep. | SAFE | `https://pypi.org/pypi/starlette/1.0.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=starlette&resultsPerPage=5`<br>`https://github.com/advisories?query=starlette` |
| typing-extensions | 4.15.0 | No exact-version PyPI advisory. NVD keyword search total=`0`; no advisory affecting `4.15.0` was confirmed. | SAFE | `https://pypi.org/pypi/typing-extensions/4.15.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=typing-extensions&resultsPerPage=5`<br>`https://github.com/advisories?query=typing-extensions` |
| typing-inspection | 0.4.2 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/typing-inspection/0.4.2/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=typing-inspection&resultsPerPage=5`<br>`https://github.com/advisories?query=typing-inspection` |
| uvicorn[standard] | 0.44.0 | No exact-version PyPI advisory. NVD keyword search total=`4`; no advisory affecting `0.44.0` was confirmed. | SAFE | `https://pypi.org/pypi/uvicorn/0.44.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=uvicorn&resultsPerPage=5`<br>`https://github.com/advisories?query=uvicorn` |
| uvloop | 0.22.1 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/uvloop/0.22.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=uvloop&resultsPerPage=5`<br>`https://github.com/advisories?query=uvloop` |
| watchfiles | 1.1.1 | No exact-version PyPI advisory. NVD keyword search total=`0`; GH advisories search=`0`. | SAFE | `https://pypi.org/pypi/watchfiles/1.1.1/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=watchfiles&resultsPerPage=5`<br>`https://github.com/advisories?query=watchfiles` |
| websockets | 16.0 | No exact-version PyPI advisory. NVD keyword search total=`54`; no advisory affecting `16.0` was confirmed. | SAFE | `https://pypi.org/pypi/websockets/16.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=websockets&resultsPerPage=5`<br>`https://github.com/advisories?query=websockets` |
| wheel | 0.46.3 | No exact-version PyPI advisory. NVD keyword search total=`37` is keyword-noisy; no wheel-package advisory affecting `0.46.3` was confirmed. | SAFE | `https://pypi.org/pypi/wheel/0.46.3/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=wheel&resultsPerPage=5`<br>`https://github.com/advisories?query=wheel` |
| yarl | 1.23.0 | No exact-version PyPI advisory. NVD keyword search total=`1`; no advisory affecting `1.23.0` was confirmed. | SAFE | `https://pypi.org/pypi/yarl/1.23.0/json`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=yarl&resultsPerPage=5`<br>`https://github.com/advisories?query=yarl` |
| hatchling | UNPINNED | No exact-version verdict possible because `[build-system]` leaves the backend floating. This is a build-chain hardening gap, not a confirmed CVE at a known version. | UNKNOWN | `https://github.com/advisories?query=hatchling`<br>`https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=hatchling&resultsPerPage=5` |

## Build-chain notes

Packages relevant to the build chain:

- `build==1.4.2`: exact-version PyPI advisory feed clean
- `pip-tools==7.5.3`: exact-version PyPI advisory feed clean
- `pyproject-hooks==1.2.0`: exact-version PyPI advisory feed clean
- `wheel==0.46.3`: exact-version PyPI advisory feed clean
- `hatchling`: not pinned, so no exact-version build-chain verdict is possible

The missing-hashes issue is still the larger immediate supply-chain problem, because even fully pinned versions without hashes leave artifact integrity to the transport/index path.

## Final verdict

- Confirmed vulnerable exact pins: `0`
- Dependencies that should be treated as requiring hardening work anyway: `2`
  - `requirements-lock.txt` without hashes
  - unpinned `hatchling` build backend

This sweep does **not** support the claim that CryoDAQ is currently shipping known-CVE-pinned Python dependencies. It **does** support the claim that the packaging pipeline still falls short of a fully reproducible, hash-verified supply chain.
