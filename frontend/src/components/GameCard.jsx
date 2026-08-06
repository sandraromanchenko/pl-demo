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

export default function GameCard({ game }) {
  const score = typeof game.score === "number" ? game.score.toFixed(4) : null;
  return (
    <div className="flex gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md">
      {game.thumbnail ? (
        <img
          src={game.thumbnail}
          alt={game.name}
          className="h-24 w-24 flex-shrink-0 rounded-lg object-cover bg-slate-100"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="truncate text-lg font-semibold text-slate-900">
            {game.name}
            {game.yearPublished ? (
              <span className="ml-2 text-sm font-normal text-slate-400">
                ({game.yearPublished})
              </span>
            ) : null}
          </h3>
          {score ? (
            <span className="flex-shrink-0 rounded-md bg-indigo-50 px-2 py-1 text-xs font-mono font-semibold text-indigo-700">
              {score}
            </span>
          ) : null}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500">
          {game.averageRating ? (
            <span className="font-medium text-amber-600">
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
          {game.complexity ? <span>weight {game.complexity}</span> : null}
        </div>

        {game.description ? (
          <p className="mt-2 line-clamp-2 text-sm text-slate-600">
            {game.description}
          </p>
        ) : null}

        <Chips items={game.categories} className="bg-emerald-50 text-emerald-700" />
        <Chips items={game.mechanics} className="bg-sky-50 text-sky-700" />
      </div>
    </div>
  );
}
