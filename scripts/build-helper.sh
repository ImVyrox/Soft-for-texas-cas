#!/usr/bin/env bash
# Compila el programa auxiliar USB (native/tcm-link) contra libticalcs2 del sistema.
set -euo pipefail
cd "$(dirname "$0")/../native/tcm-link"
for pkg in ticalcs2 ticables2 glib-2.0; do
  pkg-config --exists "$pkg" || { echo "Falta $pkg (en Arch: paquetes libticalcs, libticables, glib2)" >&2; exit 1; }
done
make
echo "Compilado: $(pwd)/tcm-link"
