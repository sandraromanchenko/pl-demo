import { useEffect, useState } from "react";
import { fetchModels, search } from "./api";
import GameCard from "./components/GameCard.jsx";

const SEARCH_TYPES = [
  { id: "fulltext", label: "Full-text", hint: "$search over name / description / categories / mechanics" },
  { id: "vector", label: "Vector", hint: "$vectorSearch on auto-embedded text" },
  { id: "hybrid", label: "Hybrid", hint: "full-text + vector merged with RRF" },
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

  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data.models || []);
        setModel(data.default || (data.models?.[0]?.model ?? ""));
      })
      .catch((e) => setError(`Could not load models: ${e.message}`));
  }, []);

  const needsModel = type !== "fulltext";

  async function runSearch(e) {
    e?.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
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
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-4 py-6">
          <h1 className="text-2xl font-bold tracking-tight">
            🎲 Board Games Search
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Full-text, vector and hybrid search powered by MongoDB Search
            (mongot) with auto-embedding.
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-6">
        <form onSubmit={runSearch} className="space-y-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search board games…"
              className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-base shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Searching…" : "Search"}
            </button>
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-500">
                Search type
              </label>
              <div className="mt-1 inline-flex rounded-lg border border-slate-300 bg-white p-0.5">
                {SEARCH_TYPES.map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    title={st.hint}
                    onClick={() => setType(st.id)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                      type === st.id
                        ? "bg-indigo-600 text-white"
                        : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {st.label}
                  </button>
                ))}
              </div>
            </div>

            <div className={needsModel ? "" : "opacity-40"}>
              <label className="block text-xs font-medium uppercase tracking-wide text-slate-500">
                Embedding model / index
              </label>
              <select
                value={model}
                disabled={!needsModel}
                onChange={(e) => setModel(e.target.value)}
                className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed"
              >
                {models.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.model} → {m.index}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-xs text-slate-400">
            {SEARCH_TYPES.find((st) => st.id === type)?.hint}
          </p>
        </form>

        {error ? (
          <div className="mt-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {meta ? (
          <p className="mt-6 text-sm text-slate-500">
            {meta.count} result{meta.count === 1 ? "" : "s"} · {meta.type}
            {meta.model ? ` · ${meta.model}` : ""}
          </p>
        ) : null}

        <div className="mt-3 space-y-3">
          {results.map((game) => (
            <GameCard key={game._id} game={game} />
          ))}
          {!loading && meta && results.length === 0 ? (
            <p className="py-12 text-center text-slate-400">No games found.</p>
          ) : null}
        </div>
      </main>
    </div>
  );
}
