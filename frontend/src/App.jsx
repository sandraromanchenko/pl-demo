import { useRef, useState } from "react";
import { search } from "./api";
import Ask from "./components/Ask.jsx";
import GameCard from "./components/GameCard.jsx";

const LIMIT = 10;

// Search type only applies to PSMDB + mongot. OpenSearch always does vector search.
const SEARCH_TYPES = [
  { id: "vector", label: "Vector" },
  { id: "fulltext", label: "Full-text" },
];

const ENGINES = [
  { id: "mongot", label: "PSMDB + mongot", hint: "Lucene HNSW" },
  { id: "opensearch", label: "OpenSearch", hint: "Faiss HNSW" },
];

// Always visible, whichever engines are on. An example only fills in the question. It never
// changes the engines or the search type: the person on stage picks those.
const EXAMPLES = [
  { q: "zombie", label: "zombie" },
  { q: "zombei", label: "zombei" },
  { q: "urban apocalypse", label: "urban apocalypse" },
  { q: "fast cars and racing", label: "fast cars and racing" },
  { q: "detective murder mystery", label: "detective murder mystery" },
  { q: "cozy gardening game", label: "cozy gardening game" },
];

const TABS = [
  { id: "search", label: "Search" },
  { id: "ask", label: "Ask" },
];

const EMPTY = { loading: false, error: null, results: [], meta: null };

export default function App() {
  const [tab, setTab] = useState("search");
  const [q, setQ] = useState("");
  const [type, setType] = useState("vector");
  const [enabled, setEnabled] = useState({ mongot: true, opensearch: false });
  const [panels, setPanels] = useState({ mongot: EMPTY, opensearch: EMPTY });
  // A slow answer from an earlier search must not overwrite a newer one.
  const runId = useRef({ mongot: 0, opensearch: 0 });

  const mongotOn = enabled.mongot;
  const both = tab === "search" && enabled.mongot && enabled.opensearch;

  function setPanel(engine, patch) {
    setPanels((p) => ({ ...p, [engine]: { ...p[engine], ...patch } }));
  }

  async function runEngine(engine, query, searchType) {
    const id = ++runId.current[engine];
    setPanel(engine, { loading: true, error: null });
    try {
      const data = await search({ q: query, type: searchType, engine, limit: LIMIT });
      if (id !== runId.current[engine]) return;
      setPanel(engine, {
        loading: false,
        results: data.results || [],
        meta: { count: data.count, type: data.type, latencyMs: data.latencyMs },
      });
    } catch (err) {
      if (id !== runId.current[engine]) return;
      setPanel(engine, { loading: false, error: err.message, results: [], meta: null });
    }
  }

  function runAll(query = q, searchType = type, on = enabled) {
    const text = query.trim();
    if (!text) return;
    for (const e of ENGINES) {
      if (on[e.id]) runEngine(e.id, text, searchType);
    }
  }

  function toggleEngine(id) {
    const next = { ...enabled, [id]: !enabled[id] };
    if (!next.mongot && !next.opensearch) return; // at least one engine stays on
    setEnabled(next);
    if (next[id]) {
      // Only the engine that just came on needs an answer.
      const text = q.trim();
      if (text) runEngine(id, text, type);
    }
  }

  function chooseType(id) {
    setType(id);
    if (q.trim()) runEngine("mongot", q.trim(), id);
  }

  function ask(query) {
    setQ(query);
    runAll(query);
  }

  function handleSubmit(e) {
    e.preventDefault();
    runAll();
  }

  const shown = ENGINES.filter((e) => enabled[e.id]);

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
        <div
          className={`relative mx-auto flex items-center gap-5 px-4 py-6 ${
            both ? "max-w-7xl" : "max-w-4xl"
          }`}
        >
          <img
            src="/percona-logo-white.svg"
            alt="Percona"
            className="h-10 w-auto flex-shrink-0"
          />
          <div className="border-l border-brand-line pl-5">
            <h1 className="text-2xl font-extrabold tracking-tight text-white">
              Board Game Search
            </h1>
          </div>
        </div>
        <nav
          className={`relative mx-auto flex gap-1 px-4 ${both ? "max-w-7xl" : "max-w-4xl"}`}
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-bold transition ${
                tab === t.id
                  ? "border-brand-volt text-white"
                  : "border-transparent text-brand-muted hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className={`mx-auto px-4 py-6 ${both ? "max-w-7xl" : "max-w-4xl"}`}>
        <div className={tab === "ask" ? "" : "hidden"}>
          <Ask />
        </div>
        <div className={tab === "search" ? "" : "hidden"}>
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
              className="rounded-lg bg-brand-volt px-5 py-2.5 font-bold text-brand-deep shadow-sm transition hover:brightness-110 disabled:opacity-50"
            >
              Search
            </button>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">
              Search examples
            </p>
            <div className="mt-1 flex flex-wrap gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.label}
                  type="button"
                  onClick={() => ask(ex.q)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    q === ex.q
                      ? "border-brand-grape bg-brand-grape text-white"
                      : "border-brand-line bg-brand-deep text-brand-muted hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {ex.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-6">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-brand-muted">
                Engines
              </label>
              <div className="mt-1 inline-flex gap-1 rounded-lg border border-brand-line bg-brand-deep p-0.5">
                {ENGINES.map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    aria-pressed={enabled[e.id]}
                    onClick={() => toggleEngine(e.id)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                      enabled[e.id]
                        ? "bg-brand-grape text-white"
                        : "text-brand-muted hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {e.label}
                  </button>
                ))}
              </div>
            </div>

            {mongotOn ? (
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wide text-brand-muted">
                  Search type{both ? " (PSMDB + mongot)" : ""}
                </label>
                <div className="mt-1 inline-flex rounded-lg border border-brand-line bg-brand-deep p-0.5">
                  {SEARCH_TYPES.map((st) => (
                    <button
                      key={st.id}
                      type="button"
                      onClick={() => chooseType(st.id)}
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
            ) : null}
          </div>
        </form>

        <div className={`mt-6 grid gap-6 ${both ? "md:grid-cols-2" : "grid-cols-1"}`}>
          {shown.map((e) => (
            <Column
              key={e.id}
              engine={e}
              panel={panels[e.id]}
              type={e.id === "mongot" ? type : "vector"}
              onTryText={e.id === "mongot" ? () => chooseType("fulltext") : null}
            />
          ))}
        </div>
        </div>

        <footer className="mt-12 border-t border-brand-line pt-4 text-xs text-brand-muted">
          Percona Search for MongoDB
        </footer>
      </main>
    </div>
  );
}

function Column({ engine, panel, type, onTryText }) {
  const { loading, error, results, meta } = panel;
  const short = meta && type === "vector" && meta.count < LIMIT;
  return (
    <section>
      <div className="flex items-baseline justify-between border-b border-brand-line pb-2">
        <h2 className="text-lg font-bold text-white">{engine.label}</h2>
        <span className="text-xs text-brand-muted">
          {type === "vector" ? `vector · ${engine.hint}` : type}
        </span>
      </div>

      {error ? (
        <div className="mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
          {onTryText && type !== "fulltext" ? (
            <button
              type="button"
              onClick={onTryText}
              className="mt-2 block font-semibold text-brand-volt underline hover:no-underline"
            >
              Try Full-text search instead
            </button>
          ) : null}
        </div>
      ) : null}

      {loading ? <p className="mt-3 text-sm text-brand-muted">Searching…</p> : null}

      {meta && !loading ? (
        <p className="mt-3 text-sm text-brand-muted">
          <span className={short ? "font-semibold text-amber-300" : "font-semibold text-white"}>
            {type === "vector" ? `${meta.count} of ${LIMIT} results` : `${meta.count} result${meta.count === 1 ? "" : "s"}`}
          </span>
          {typeof meta.latencyMs === "number" ? ` · ${meta.latencyMs} ms` : ""}
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
    </section>
  );
}
