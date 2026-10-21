#!/usr/bin/env bash
# Render every docs/diagrams/*.mmd source to an SVG next to it, using the shared
# palette and layout settings in docs/diagrams/mermaid.config.json.
#
# Requires Node.js 18+. If Chromium needs extra flags (for example --no-sandbox
# in a container), point PUPPETEER_CONFIG at a puppeteer JSON config file.
set -euo pipefail

cd "$(dirname "$0")/../docs/diagrams"

mmdc=(npx --yes @mermaid-js/mermaid-cli@11.17.0 --configFile mermaid.config.json --backgroundColor "#FFFFFF" --quiet)
if [[ -n "${PUPPETEER_CONFIG:-}" ]]; then
  mmdc+=(--puppeteerConfigFile "$PUPPETEER_CONFIG")
fi

for source in *.mmd; do
  echo "rendering ${source%.mmd}.svg"
  "${mmdc[@]}" --input "$source" --output "${source%.mmd}.svg"
done
