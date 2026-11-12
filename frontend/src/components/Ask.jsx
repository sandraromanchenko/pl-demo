import { useState } from "react";
import { ask } from "../api";

// The RAG tab: the question is embedded, the closest passages are retrieved from
// PSMDB + mongot, and a small language model writes the answer from them.
export default function Ask() {
  const [q, setQ] = useState("");
  const [state, setState] = useState({ loading: false, error: null, data: null });

  async function submit(e) {
    e.preventDefault();
    const text = q.trim();
    if (!text) return;
    setState({ loading: true, error: null, data: null });
    try {
      const data = await ask(text);
      setState({ loading: false, error: null, data });
    } catch (err) {
      setState({ loading: false, error: err.message, data: null });
    }
  }

  const { loading, error, data } = state;

  return (
    <div>
      <form onSubmit={submit} className="flex gap-2">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask for a game…"
          className="flex-1 rounded-lg border border-brand-line bg-brand-deep px-4 py-2.5 text-base text-white placeholder-brand-muted shadow-sm focus:border-brand-volt focus:outline-none focus:ring-1 focus:ring-brand-volt"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-brand-volt px-5 py-2.5 font-bold text-brand-deep shadow-sm transition hover:brightness-110 disabled:opacity-50"
        >
          Ask
        </button>
      </form>

      {loading ? <p className="mt-6 text-sm text-brand-muted">Thinking…</p> : null}

      {error ? (
        <div className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {data ? (
        <div className="mt-6">
          <div className="rounded-xl border border-brand-line bg-brand-panel p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">
              Answer
            </p>
            <p className="mt-2 whitespace-pre-wrap text-lg leading-relaxed text-white">
              {data.answer || "(empty answer)"}
            </p>
            <p className="mt-3 text-xs text-brand-muted">
              embed {data.embedMs} ms · search {data.searchMs} ms · vLLM {data.llmMs} ms
            </p>
          </div>

          <h2 className="mt-6 border-b border-brand-line pb-2 text-lg font-bold text-white">
            Sources
          </h2>
          <div className="mt-3 space-y-3">
            {(data.sources || []).map((s) => (
              <div
                key={s.id}
                className="rounded-xl border border-brand-line bg-brand-panel p-4 shadow-sm transition hover:border-brand-grape"
              >
                <h3 className="text-base font-bold text-white">{s.title || s.id}</h3>
                <p className="mt-1 text-sm text-brand-muted">{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
