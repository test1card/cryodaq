#!/bin/sh
# Put the chosen interpreter's own libstdc++ ahead of the system one.
#
# MEASURED on lab53, clean interpreters:
#
#     import pyarrow   -> binds /usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.30
#     import sqlite3   -> binds <env>/lib/libstdc++.so.6.0.36
#
#     import pyarrow; import sqlite3  -> ImportError: CXXABI_1.3.15 not found
#     import sqlite3; import pyarrow  -> fine
#
# Whichever of the two loads FIRST decides whether sqlite3 loads at all, and
# glibc fixes the search path at exec, so the correction has to happen before
# the interpreter starts. Sourced by start.sh and start_mock.sh with CRYODAQ_PY
# already resolved.
#
# SELECTION, corrected 2026-09-06 after review. The first version guarded on
#
#     [ "$CRYODAQ_PY" != "$(command -v python3 || true)" ]
#
# which skipped the correction whenever the environment's python IS the python3
# on PATH — that is, whenever the environment is properly activated, which is
# exactly the configuration that needs it. Reviewer measurement, same
# environment and interpreter, actual script with only the final exec replaced
# by an import probe: env python absent from PATH -> exit 0, SQLite 3.53.2;
# env python present on PATH -> exit 1, CXXABI_1.3.15 error.
#
# The interpreter is now asked where its own environment lives, and the
# directory is prepended only when it actually carries the library in question.
# That second test is not decoration: a system interpreter reports prefix /usr,
# whose libstdc++ lives in a multiarch subdirectory, so the check is what keeps
# /usr/lib from being pushed in front of the loader's normal search order.

if [ -n "$CRYODAQ_PY" ] && [ -x "$CRYODAQ_PY" ]; then
    # Both prefixes: inside a virtualenv layered on the conda environment,
    # sys.prefix is the venv and carries no libstdc++, while sys.base_prefix is
    # the environment that does.
    for _cryodaq_prefix in \
        "$("$CRYODAQ_PY" -c 'import sys; print(sys.prefix)' 2>/dev/null || true)" \
        "$("$CRYODAQ_PY" -c 'import sys; print(sys.base_prefix)' 2>/dev/null || true)"
    do
        [ -n "$_cryodaq_prefix" ] || continue
        _cryodaq_lib="$_cryodaq_prefix/lib"
        [ -e "$_cryodaq_lib/libstdc++.so.6" ] || continue
        case ":${LD_LIBRARY_PATH:-}:" in
            *":$_cryodaq_lib:"*) ;;  # already first or present; do not duplicate
            *) export LD_LIBRARY_PATH="$_cryodaq_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
        esac
        break
    done
    unset _cryodaq_prefix _cryodaq_lib
fi
