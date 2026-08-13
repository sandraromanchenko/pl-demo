import { useEffect, useState } from "react";
import { fetchModels, search } from "./api";
import GameCard from "./components/GameCard.jsx";

const SEARCH_TYPES = [
  {
    id: "fulltext",
    label: "Full-text",
    hint: "$search over name, description, categories, and mechanics",
  },
  {
    id: "vector",
    label: "Vector",
    hint: "$vectorSearch on auto-embedded query text",
  },
  {
    id: "hybrid",
    label: "Hybrid",
    hint: "Full-text + vector merged with reciprocal rank fusion",
  },
];

const EXAMPLES = [
  "cooperative deck building",
  "engine building economic",
  "two player abstract strategy",
  "legacy campaign storytelling",
];

export default function App() {
  const [q, setQ] = useState("cooperative deck building");
  const [type, setType] = useState("fulltext");
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [results, setResults] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data.models || []);
        setModel(data.default || (data.models?.[0]?.model ?? ""));
      })
      .catch((e) => setError(`Could not load models: ${e.message}`));
  }, []);

  const needsModel = type !== "fulltext";
  const typeIndex = Math.max(
    0,
    SEARCH_TYPES.findIndex((st) => st.id === type)
  );

  async function runSearch(e) {
    e?.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const data = await search({ q, type, model, limit: 5 });
      setResults(data.results || []);
      setMeta({ count: data.count, type: data.type, model: data.model });
    } catch (err) {
      setError(err.message);
      setResults([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      <div className="hex-grid pointer-events-none absolute inset-0" aria-hidden />

      <header className="relative mx-auto max-w-5xl px-5 pb-2 pt-10 sm:px-8 sm:pt-14">
        <p className="animate-rise font-display text-xs font-bold uppercase tracking-[0.28em] text-fern">
          Percona · MongoDB Search
        </p>
        <h1 className="animate-rise-delay mt-3 font-display text-5xl font-extrabold leading-[0.95] tracking-tight text-ink sm:text-6xl md:text-7xl">
          Board Games
          <span className="mt-1 block text-pine">Search</span>
        </h1>
        <p className="animate-rise-delay-2 mt-5 max-w-xl text-base leading-relaxed text-ink/70 sm:text-lg">
          Full-text, vector, and hybrid retrieval over ~20k titles — powered by
          mongot auto-embedding.
        </p>
      </header>

      <main className="relative mx-auto max-w-5xl px-5 pb-16 sm:px-8">
        <form
          onSubmit={runSearch}
          className="search-shell animate-rise-delay-2 mt-8 p-4 sm:p-5"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
            <label className="sr-only" htmlFor="q">
              Search board games
            </label>
            <input
              id="q"
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Describe a game, mechanic, or vibe…"
              className="min-w-0 flex-1 rounded-xl border border-line/12 bg-white/70 px-4 py-3.5 text-base text-ink placeholder:text-ink/35 outline-none transition focus:border-fern focus:bg-white"
            />
            <button
              type="submit"
              disabled={loading}
              className="rounded-xl bg-pine px-6 py-3.5 font-display text-base font-bold text-paper transition hover:bg-fern disabled:cursor-wait disabled:opacity-60"
            >
              {loading ? "Searching…" : "Search"}
            </button>
          </div>

          <div className="mt-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.18em] text-ink/45">
                Search type
              </span>
              <div className="type-track" role="tablist" aria-label="Search type">
                <span
                  className="type-thumb"
                  style={{ transform: `translateX(calc(${typeIndex} * 100%))` }}
                  aria-hidden
                />
                {SEARCH_TYPES.map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    role="tab"
                    aria-selected={type === st.id}
                    title={st.hint}
                    onClick={() => setType(st.id)}
                    className={`relative z-10 px-3 py-2 text-sm font-semibold transition ${
                      type === st.id ? "text-paper" : "text-ink/65 hover:text-ink"
                    }`}
                  >
                    {st.label}
                  </button>
                ))}
              </div>
            </div>

            <div className={`min-w-[14rem] ${needsModel ? "" : "opacity-40"}`}>
              <label
                htmlFor="model"
                className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.18em] text-ink/45"
              >
                Embedding model
              </label>
              <select
                id="model"
                value={model}
                disabled={!needsModel}
                onChange={(e) => setModel(e.target.value)}
                className="w-full rounded-xl border border-line/12 bg-white/70 px-3 py-2.5 text-sm font-medium text-ink outline-none transition focus:border-fern disabled:cursor-not-allowed"
              >
                {models.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.model} → {m.index}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <p className="mt-3 text-sm text-ink/50">
            {SEARCH_TYPES.find((st) => st.id === type)?.hint}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line/12 pt-4 text-sm">
            <span className="font-medium text-ink/40">Try</span>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setQ(example)}
                className="text-left text-fern underline decoration-fern/30 underline-offset-4 transition hover:text-pine hover:decoration-pine"
              >
                {example}
              </button>
            ))}
          </div>
        </form>

        {loading ? (
          <div className="mt-10" aria-live="polite" aria-busy="true">
            <div className="h-1 origin-left rounded-full bg-butter animate-pulse-bar" />
            <p className="mt-4 text-sm text-ink/50">Querying mongot…</p>
          </div>
        ) : null}

        {error ? (
          <div
            className="mt-8 rounded-xl border border-clay/30 bg-clay/10 px-4 py-3 text-sm text-clay"
            role="alert"
          >
            {error}
          </div>
        ) : null}

        {!loading && meta ? (
          <section className="mt-10 animate-fade">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-display text-2xl font-bold tracking-tight text-ink">
                Results
              </h2>
              <p className="text-sm text-ink/50">
                {meta.count} match{meta.count === 1 ? "" : "es"} · {meta.type}
                {meta.model ? ` · ${meta.model}` : ""}
              </p>
            </div>
            <div className="rounded-2xl border border-line/12 bg-paper/55 px-4 backdrop-blur-sm sm:px-6">
              {results.map((game, i) => (
                <GameCard key={game._id} game={game} index={i} />
              ))}
              {results.length === 0 ? (
                <p className="py-14 text-center text-ink/40">No games found.</p>
              ) : null}
            </div>
          </section>
        ) : null}

        {!loading && !meta && !error && !searched ? (
          <p className="mt-12 max-w-md text-sm leading-relaxed text-ink/40">
            Pick a mode, refine the query, and search. Vector and hybrid use the
            selected embedding index.
          </p>
        ) : null}
      </main>
    </div>
  );
}
