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

export function search({ q, type, model, limit = 5 }) {
  const params = new URLSearchParams({ q, type, limit: String(limit) });
  if (model && (type === "vector" || type === "hybrid")) params.set("model", model);
  return getJSON(`/search?${params.toString()}`);
}
