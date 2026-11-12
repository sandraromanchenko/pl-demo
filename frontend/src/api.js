// API client. VITE_API_BASE is baked in at build time; falls back to same-origin.
const API_BASE = import.meta.env.VITE_API_BASE || "";

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function fetchModels() {
  return getJSON("/models");
}

export function fetchGames({ limit = 100 } = {}) {
  return getJSON(`/games?limit=${limit}`);
}

// The RAG assistant sits behind the frontend's own nginx (/rag/), so no CORS and no extra port.
export async function ask(q) {
  let res;
  try {
    res = await fetch("/rag/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q }),
    });
  } catch (_) {
    throw new Error("The assistant is not reachable.");
  }
  const raw = await res.text();
  if (res.status === 502 && raw.includes("<html")) {
    throw new Error("The assistant is not running (make osmc-rag-up).");
  }
  if (!res.ok) throw new Error(raw.trim() || res.statusText);
  return JSON.parse(raw);
}

// engine: "mongot" (PSMDB + mongot, any search type) or "opensearch" (vector only).
export function search({ q, type, engine = "mongot", model, limit = 10 }) {
  const params = new URLSearchParams({ q, type, engine, limit: String(limit) });
  if (model && (type === "vector" || type === "hybrid")) params.set("model", model);
  return getJSON(`/search?${params.toString()}`);
}
