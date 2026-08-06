# Data directory

The board-game dataset lives here as **`data/boardgames.ndjson`** (one JSON object per line)
Pick which set the `seed` service loads with the **`DATASET`** env var:
- `DATASET=sample` (default) → `data/sample_boardgames.ndjson`, 20 real games with the same schema, for a fast local run
- `DATASET=full` → `data/boardgames.ndjson` (falls back to the sample if the file is missing)

## Expected document schema

Each line is a single board game. `search_text` is **built by the seed loader**
(name + description), so you do not need to include it yourself.

| Field | Type | Notes |
|-------|------|-------|
| `_id` | int/string | Stable id (e.g. BGG id). Used for idempotent upserts. |
| `name` | string | Indexed for full-text + part of `search_text`. |
| `yearPublished` | int | |
| `description` | string | Indexed for full-text + part of `search_text`. |
| `minPlayers` | int | |
| `maxPlayers` | int | |
| `playingTime` | int | Minutes. |
| `minAge` | int | |
| `categories` | string[] | Indexed for full-text. |
| `mechanics` | string[] | Indexed for full-text. |
| `designers` | string[] | |
| `averageRating` | float | |
| `rank` | int | Overall rank; a btree index is created for sorting. |
| `complexity` | float | BGG "weight" 1–5. |
| `thumbnail` | string | Image URL, shown on the result card. |
| `search_text` | string | **Auto-built by seed** (name + description); autoEmbed path. |

### Example line

```json
{"_id": 174430, "name": "Gloomhaven", "yearPublished": 2017, "description": "A cooperative campaign game...", "minPlayers": 1, "maxPlayers": 4, "playingTime": 120, "minAge": 14, "categories": ["Adventure"], "mechanics": ["Cooperative Game"], "designers": ["Isaac Childres"], "averageRating": 8.6, "rank": 1, "complexity": 3.9, "thumbnail": "https://.../gloomhaven.jpg"}
```

### Descriptions

In `boardgames.ndjson` the top ~2000 games have clean, readable one-line
descriptions; the long tail keeps lemmatized/stripped text (fine for search,
ugly for display).