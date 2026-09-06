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
        # FIRST, not merely present. The previous version treated "the
        # directory appears somewhere" as "the directory wins" — its own comment
        # said "already first or present", which is exactly the conflation.
        # Reviewer reproduced it through the real start.sh with only the final
        # launch replaced by an import probe: environment library first, imports
        # succeed; system library first with the environment library already
        # second, CXXABI_1.3.15 failure. Being on the path decides nothing; only
        # being ahead of the system one does.
        #
        # Any existing occurrence is removed and the directory is prepended, so
        # the remaining entries keep their order and nothing is duplicated.
        _cryodaq_rest=""
        _cryodaq_ifs="$IFS"
        IFS=":"
        for _cryodaq_entry in ${LD_LIBRARY_PATH:-}; do
            [ -n "$_cryodaq_entry" ] || continue
            [ "$_cryodaq_entry" = "$_cryodaq_lib" ] && continue
            _cryodaq_rest="${_cryodaq_rest:+$_cryodaq_rest:}$_cryodaq_entry"
        done
        IFS="$_cryodaq_ifs"
        export LD_LIBRARY_PATH="$_cryodaq_lib${_cryodaq_rest:+:$_cryodaq_rest}"
        unset _cryodaq_rest _cryodaq_ifs _cryodaq_entry
        break
    done
    unset _cryodaq_prefix _cryodaq_lib
fi
