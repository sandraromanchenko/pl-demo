import { useLayoutEffect, useRef, useState } from "react";

function Chips({ items, className }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {items.slice(0, 6).map((item) => (
        <span
          key={item}
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${className}`}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

// A BoardGameGeek "weight" (1-5) means nothing to most people, so the API tags
// every result with a band ("Easy", "~15 min to learn"). Only the colour is a
// frontend concern.
const BAND_COLORS = {
  easy: "bg-emerald-400/15 text-emerald-300",
  medium: "bg-brand-volt/15 text-brand-volt",
  complex: "bg-orange-400/15 text-orange-300",
};

export default function GameCard({ game }) {
  const score = typeof game.score === "number" ? game.score.toFixed(4) : null;
  const complexity = Number(game.complexity);
  const band = game.complexityBand;
  const localThumb = game.thumbnail?.startsWith("/");
  return (
    <div className="flex gap-4 rounded-xl border border-brand-line bg-brand-panel p-4 shadow-sm transition hover:border-brand-grape">
      {game.thumbnail ? (
        <img
          src={game.thumbnail}
          alt={game.name}
          className={`h-24 w-24 flex-shrink-0 rounded-lg ${
            localThumb
              ? "bg-white object-contain p-1"
              : "bg-brand-deep object-cover"
          }`}
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="truncate text-lg font-bold text-white">
            {game.name}
            {game.yearPublished ? (
              <span className="ml-2 text-sm font-normal text-brand-muted">
                ({game.yearPublished})
              </span>
            ) : null}
          </h3>
          {score ? (
            <span
              title="Relevance score for this search mode"
              className="flex-shrink-0 rounded-md border border-brand-grape/40 bg-brand-grape/15 px-2 py-1 font-mono text-xs font-semibold text-brand-volt"
            >
              {score}
            </span>
          ) : null}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-brand-muted">
          {game.averageRating ? (
            <span className="font-semibold text-brand-volt">
              ★ {Number(game.averageRating).toFixed(1)}
            </span>
          ) : null}
          {game.rank ? <span>#{game.rank}</span> : null}
          {game.minPlayers ? (
            <span>
              {game.minPlayers}
              {game.maxPlayers && game.maxPlayers !== game.minPlayers
                ? `–${game.maxPlayers}`
                : ""}{" "}
              players
            </span>
          ) : null}
          {game.playingTime ? <span>{game.playingTime} min</span> : null}
          {game.minAge ? <span>ages {game.minAge}+</span> : null}
          {band ? (
            <span
              className="inline-flex items-center gap-1.5"
              title={`BoardGameGeek complexity ${complexity.toFixed(2)} of 5`}
            >
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                  BAND_COLORS[band.id] || "bg-white/10 text-white"
                }`}
              >
                {band.label}
              </span>
              <span>{band.learn}</span>
            </span>
          ) : null}
        </div>

        <Description text={game.description} />

        <Chips
          items={game.categories}
          className="bg-brand-grape/20 text-indigo-200"
        />
        <Chips items={game.mechanics} className="bg-white/5 text-brand-muted" />
      </div>
    </div>
  );
}

function Description({ text }) {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef(null);

  useLayoutEffect(() => {
    setExpanded(false);
  }, [text]);

  useLayoutEffect(() => {
    if (expanded) return;
    const el = ref.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, expanded]);

  if (!text) return null;

  return (
    <div className="mt-2">
      <p
        ref={ref}
        className={`whitespace-pre-line text-sm text-slate-300 ${
          expanded ? "" : "line-clamp-5"
        }`}
      >
        {text}
      </p>
      {overflows || expanded ? (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-sm font-semibold text-brand-volt hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      ) : null}
    </div>
  );
}
