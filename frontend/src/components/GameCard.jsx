function TagList({ items, tone }) {
  if (!items || items.length === 0) return null;
  const tones = {
    category: "text-fern",
    mechanic: "text-clay",
  };
  return (
    <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs font-medium">
      {items.slice(0, 5).map((item) => (
        <li key={item} className={tones[tone] || "text-ink/55"}>
          {item}
        </li>
      ))}
    </ul>
  );
}

export default function GameCard({ game, index = 0 }) {
  const score = typeof game.score === "number" ? game.score.toFixed(4) : null;
  const players =
    game.minPlayers != null
      ? `${game.minPlayers}${
          game.maxPlayers && game.maxPlayers !== game.minPlayers
            ? `–${game.maxPlayers}`
            : ""
        } players`
      : null;

  return (
    <article
      className="result-row animate-rise"
      style={{ animationDelay: `${Math.min(index, 6) * 55}ms` }}
    >
      <div className="relative h-24 w-full overflow-hidden rounded-xl bg-mist sm:h-28">
        {game.thumbnail ? (
          <img
            src={game.thumbnail}
            alt=""
            className="h-full w-full object-cover transition duration-500 hover:scale-105"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center font-display text-2xl font-bold text-pine/30">
            {(game.name || "?").slice(0, 1)}
          </div>
        )}
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="font-display text-xl font-bold tracking-tight text-ink">
            {game.name}
          </h3>
          {game.yearPublished ? (
            <span className="text-sm text-ink/40">{game.yearPublished}</span>
          ) : null}
        </div>

        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink/55">
          {game.averageRating ? (
            <div className="flex gap-1.5">
              <dt className="sr-only">Rating</dt>
              <dd className="font-semibold text-ink">
                {Number(game.averageRating).toFixed(1)}
                <span className="ml-1 font-normal text-ink/45">rating</span>
              </dd>
            </div>
          ) : null}
          {game.rank ? (
            <div>
              <dt className="sr-only">Rank</dt>
              <dd>#{game.rank}</dd>
            </div>
          ) : null}
          {players ? (
            <div>
              <dt className="sr-only">Players</dt>
              <dd>{players}</dd>
            </div>
          ) : null}
          {game.playingTime ? (
            <div>
              <dt className="sr-only">Play time</dt>
              <dd>{game.playingTime} min</dd>
            </div>
          ) : null}
          {game.complexity ? (
            <div>
              <dt className="sr-only">Complexity</dt>
              <dd>weight {game.complexity}</dd>
            </div>
          ) : null}
        </dl>

        {game.description ? (
          <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-ink/65">
            {game.description}
          </p>
        ) : null}

        <TagList items={game.categories} tone="category" />
        <TagList items={game.mechanics} tone="mechanic" />
      </div>

      {score ? (
        <div className="sm:justify-self-end sm:pt-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-ink/35">
            Score
          </p>
          <p className="mt-0.5 font-display text-lg font-bold tabular-nums text-pine">
            {score}
          </p>
        </div>
      ) : null}
    </article>
  );
}
