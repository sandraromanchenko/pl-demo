// A new game arrives after the indexes are already built.
// Nothing here is a vector: autoEmbed embeds `search_text` for us.

const game = {
  _id: 900003,
  name: "Keep It Open",
  yearPublished: 2026,

  description:
    "Rebel engineers who defend liberty: a professional cooperative " +
    "crew working against Cloudopoly, the giant that locked database " +
    "features behind a paywall. You stand with the rebels who refuse " +
    "corporate lock-in.\n\n" +

    "Your stronghold is Percona Live Amsterdam - a bastion for keeping " +
    "open source genuinely open, where engineers believe technology " +
    "should be shared, not hoarded. Between sessions and hallway coffee " +
    "you collect Insight and Code tokens to arm your team.\n\n" +

    "Three days to commit the code and defend the community's liberty " +
    "to innovate without limits. History will remember who stood with " +
    "the rebels.",

  minPlayers: 1,
  maxPlayers: 4,
  playingTime: 60,
  minAge: 12,

  categories: [
    "Economic", "Educational", "Industry / Manufacturing", "Card Game",
  ],
  mechanics: [
    "Cooperative Game", "Action Points", "Hand Management",
    "Set Collection", "Variable Player Powers",
  ],
  designers: ["The Open Source Community"],

  averageRating: 8.5,
  rank: 120,
  complexity: 2.75,
  thumbnail: "/keep-it-open.png",
};

// The autoEmbed index points at this path (same as the seed loader builds).
game.search_text = game.name + "\n" + game.description;

printjson(db.getSiblingDB("boardgames").games.insertOne(game));
