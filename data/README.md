# Data directory

The seed loader reads **`data/sample_boardgames.ndjson`** (one JSON object per
line): 50 games with full descriptions and cover art — BGG ranks 1–50, minus
*Great Western Trail: Second Edition* (a near-duplicate of the rank-21 original)
and plus *Zombicide* (rank 521), which gives the set a zombie/horror theme that
nothing else in the top 50 covers. Lines are ordered by `rank`.

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

Descriptions are the full BoardGameGeek text for each game, cleaned of HTML.
