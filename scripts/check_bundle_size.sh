#!/usr/bin/env bash
# Presupuesto de tamaño de assets (Fase 7).
# Falla si el CSS compilado de Tailwind supera el límite. Evita que el bundle
# crezca sin querer (clases sin purgar, imports pesados) y degrade la carga en
# mobile. Corré primero `npm --prefix theme/static_src run build`.
#
# NO chequeamos JS: htmx y Alpine se sirven desde unpkg (no son bundle propio);
# el único JS propio es inline en los templates (mínimo).
set -euo pipefail

MAX_CSS_KB="${MAX_CSS_KB:-90}"
CSS_FILE="theme/static/css/dist/styles.css"

if [[ ! -f "$CSS_FILE" ]]; then
  echo "ERROR: no existe $CSS_FILE — corré 'npm --prefix theme/static_src run build' primero." >&2
  exit 2
fi

# Tamaño en KB (redondeado hacia arriba con du -k, que ya redondea por bloque).
CSS_KB=$(du -k "$CSS_FILE" | cut -f1)

echo "CSS bundle: ${CSS_KB} KB (límite ${MAX_CSS_KB} KB) — $CSS_FILE"

if (( CSS_KB > MAX_CSS_KB )); then
  echo "FALLO: el CSS (${CSS_KB} KB) supera el presupuesto (${MAX_CSS_KB} KB)." >&2
  echo "Revisá clases sin usar o @source de más en theme/static_src/src/styles.css." >&2
  exit 1
fi

echo "OK: dentro del presupuesto."
