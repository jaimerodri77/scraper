name: Tennis Scraper Diario

on:
  schedule:
    - cron: '0 8 * * *'
  workflow_dispatch:

jobs:
  scrape:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repositorio
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Instalar dependencias
        run: pip install pandas requests

      - name: Ejecutar scraper
        run: python scraper.py

      - name: Guardar datos en repositorio
        run: |
          git config --global user.email "scraperbot@github.com"
          git config --global user.name "TennisScraperBot"
          [ -f datos ] && rm datos
          mkdir -p datos
          git add --all datos/ || true
          if git diff --staged --quiet; then
            echo "Sin cambios nuevos, nada que commitear."
            exit 0
          fi
          git commit -m "Update tennis data $(date +'%Y-%m-%d')"
          git push
