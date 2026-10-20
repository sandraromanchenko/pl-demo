import { useEffect, useState } from "react";
import { fetchGames, fetchModels, search } from "./api";
import GameCard from "./components/GameCard.jsx";

const SEARCH_TYPES = [
  { id: "text", label: "Text" },
  { id: "fulltext", label: "Full-text" },
  { id: "vector", label: "Vector" },
];

// One query per mode, each checked against the sample dataset: "zombie" is a
// whole token so $text finds Zombicide, "zombei" is a typo only fuzzy $search
// survives, and "urban apocalypse" appears nowhere in the indexed fields and is
// further than maxEdits from every token, so it returns nothing in either
// keyword mode and only vector search finds Zombicide.
const EXAMPLES = [
  { q: "zombie", label: "text" },
  { q: "zombei", label: "typo" },
  { q: "urban apocalypse", label: "context" },
];

export default function App() {
  // Empty query so the page opens with no results. Text is the demo's starting
  // engine: classic $text works before mongot exists (see demo/README.md).
  const [q, setQ] = useState("");
  const [type, setType] = useState("text");
  const [models, setModels] = useState([]);
  const [model, setModel] = useState("");
  const [results, setResults] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data.models || []);
        setModel(data.default || (data.models?.[0]?.model ?? ""));
      })
      .catch((e) => setError(`Could not load models: ${e.message}`));
  }, []);

  const needsModel = type === "vector" || type === "hybrid";

  async function loadBrowse() {
    try {
      const data = await fetchGames();
      setResults(data.results || []);
      setMeta({ browse: true, total: data.total });
      setError(null);
    } catch (e) {
      setError(`Could not load games: ${e.message}`);
    }
  }

  async function runSearch(e, query, searchType = type) {
    e?.preventDefault();
    const qText = (query ?? q).trim();
    if (!qText) return;
    setLoading(true);
    setError(null);
    try {
      const data = await search({ q: qText, type: searchType, model, limit: 5 });
      setResults(data.results || []);
      setMeta({
        count: data.count,
        type: data.type,
        model: data.model,
      });
    } catch (err) {
      setError(err.message);
      setResults([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }

  // Text with no query → show the corpus. Full-text / Vector with no query →
  // probe the engine so a pre-mongot stack still surfaces the 503 on screen
  // (otherwise the browse list looks like those modes already work). With a
  // query, re-run on every engine change so Text vs Full-text is one click.
  useEffect(() => {
    let cancelled = false;

    async function syncEngine() {
      if (q.trim()) {
        await runSearch(undefined, q, type);
        return;
      }
      if (type === "text") {
        await loadBrowse();
        return;
      }
      // Probe: discard hits; we only care whether the engine is available.
      setLoading(true);
      setError(null);
      try {
        await search({ q: "ping", type, model, limit: 1 });
        if (cancelled) return;
        setResults([]);
        setMeta(null);
      } catch (err) {
        if (cancelled) return;
        setError(err.message);
        setResults([]);
        setMeta(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    syncEngine();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- type/model/q drive sync
  }, [type, model]);

  // Example chips always restart from classic $text (demo walk-up). Search
  // button keeps the selected engine so Full-text / Vector can fail visibly.
  function searchFromText(query) {
    if (query !== undefined) setQ(query);
    if (type === "text") {
      runSearch(undefined, query, "text");
    } else {
      setType("text");
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    runSearch(e);
  }

  return (
    <div className="min-h-screen bg-brand-bg text-white">
      {/* Title-slide layout: logo left, mountains fading in from the right. */}
      <header className="relative overflow-hidden border-b border-brand-line bg-brand-bg">
        <img
          src="/mountains.jpg"
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 hidden h-full w-1/2 object-cover opacity-60 [mask-image:linear-gradient(to_right,transparent,black_65%)] sm:block"
        />
        <div className="relative mx-auto flex max-w-4xl items-center gap-5 px-4 py-6">
          <img
            src="/percona-logo-white.svg"
            alt="Percona"
            className="h-10 w-auto flex-shrink-0"
          />
          <div className="border-l border-brand-line pl-5">
            <h1 className="text-2xl font-extrabold tracking-tight text-white">
              Board Game Search
            </h1>
            <p className="mt-1 text-sm text-brand-muted">
              See the difference: classic text, full-text and vector search in
              action
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search board games…"
              className="flex-1 rounded-lg border border-brand-line bg-brand-deep px-4 py-2.5 text-base text-white placeholder-brand-muted shadow-sm focus:border-brand-volt focus:outline-none focus:ring-1 focus:ring-brand-volt"
            />
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-brand-volt px-5 py-2.5 font-bold text-brand-deep shadow-sm transition hover:brightness-110 disabled:opacity-50"
            >
              {loading ? "Searching…" : "Search"}
            </button>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">
              Search examples
            </p>
            <div className="mt-1 flex flex-wrap gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.q}
                  type="button"
                  onClick={() => searchFromText(ex.q)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    q === ex.q
                      ? "border-brand-grape bg-brand-grape text-white"
                      : "border-brand-line bg-brand-deep text-brand-muted hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {ex.label}: {ex.q}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-brand-muted">
                Search type
              </label>
              <div className="mt-1 inline-flex rounded-lg border border-brand-line bg-brand-deep p-0.5">
                {SEARCH_TYPES.map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => setType(st.id)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                      type === st.id
                        ? "bg-brand-grape text-white"
                        : "text-brand-muted hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {st.label}
                  </button>
                ))}
              </div>
            </div>

            <div className={needsModel ? "" : "opacity-40"}>
              <label className="block text-xs font-semibold uppercase tracking-wide text-brand-muted">
                Embedding model / index
              </label>
              <select
                value={model}
                disabled={!needsModel}
                onChange={(e) => setModel(e.target.value)}
                className="mt-1 rounded-lg border border-brand-line bg-brand-deep px-3 py-1.5 text-sm text-white shadow-sm focus:border-brand-volt focus:outline-none focus:ring-1 focus:ring-brand-volt disabled:cursor-not-allowed"
              >
                {models.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.model} → {m.index}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </form>

        {error ? (
          <div className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
            {type !== "text" ? (
              // Changing the engine re-runs the search, so this both switches
              // and retries.
              <button
                type="button"
                onClick={() => setType("text")}
                className="mt-2 block font-semibold text-brand-volt underline hover:no-underline"
              >
                Try classic Text search instead
              </button>
            ) : null}
          </div>
        ) : null}

        {meta ? (
          <p className="mt-6 text-sm text-brand-muted">
            {meta.browse ? (
              <>
                Full collection ·{" "}
                <span className="font-semibold text-white">
                  {meta.total} games
                </span>
              </>
            ) : (
              <>
                {meta.count} result{meta.count === 1 ? "" : "s"} · {meta.type}
                {meta.model ? ` · ${meta.model}` : ""}
              </>
            )}
          </p>
        ) : null}

        <div className="mt-3 space-y-3">
          {results.map((game) => (
            <GameCard key={game._id} game={game} />
          ))}
          {!loading && meta && results.length === 0 ? (
            <p className="py-12 text-center text-brand-muted">No games found.</p>
          ) : null}
        </div>

        <footer className="mt-12 border-t border-brand-line pt-4 text-xs text-brand-muted">
          Percona Search for MongoDB
        </footer>
      </main>
    </div>
  );
}
