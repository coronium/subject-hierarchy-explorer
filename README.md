# Subject Hierarchy Explorer

Discovers broader/narrower relationships between IsisCB subject terms by analyzing co-occurrence patterns across ~139,000 citations.

**Live app:** Deployed on [Render](https://render.com) (see render.yaml)

## How it works

IsisCB citations are tagged with multiple subject terms. When two subjects frequently appear together on the same citations, that reveals a relationship. The direction of the relationship comes from *asymmetry*:

- If "Nephrology" almost always appears with "Medicine" (86%), but "Medicine" rarely appears with "Nephrology" (0.05%), then **Nephrology is narrower than Medicine**.
- Formally: **P(B|A) >> P(A|B)** implies A is a subcategory of B.

The app precomputes conditional probabilities for all ~13,000 meaningful subject pairs and serves them through an interactive UI.

## Running locally

```bash
# From the horus project root — compute fresh data from the IsisCB SQLite database:
cd ingest
python examples/subject_hierarchy_explorer.py

# Or use precomputed data (no SQLite needed):
cd deploy/subject-hierarchy-explorer
pip install -r requirements.txt
python app.py
# Opens at http://127.0.0.1:5030
```

## Regenerating the data file

When the IsisCB database is updated:

```bash
cd ingest
python examples/subject_hierarchy_explorer.py \
    --export-data ../deploy/subject-hierarchy-explorer/subject_cooccurrence_data.json
```

This reads the 404 MB SQLite database, computes all co-occurrence statistics, filters to meaningful relationships (co-occurrence >= 3, P >= 0.1), and writes a 3.8 MB JSON file.

## Deploying to Render

The `render.yaml` configures a free-tier web service. Connect this repo to Render and it auto-deploys. The app loads the precomputed JSON at startup (~0.1s) and serves requests via gunicorn.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask app with UI and API |
| `subject_cooccurrence_data.json` | Precomputed co-occurrence data (3.8 MB) |
| `requirements.txt` | Python dependencies (Flask, gunicorn) |
| `render.yaml` | Render deployment config |
