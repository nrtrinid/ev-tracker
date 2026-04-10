type TeamAliasEntry = {
  displayName: string;
  aliases: string[];
};

const TEAM_ALIAS_ENTRIES: TeamAliasEntry[] = [
  { displayName: "Atlanta Hawks", aliases: ["atl", "hawks"] },
  { displayName: "Boston Celtics", aliases: ["bos", "celtics"] },
  { displayName: "Brooklyn Nets", aliases: ["bkn", "nets"] },
  { displayName: "Charlotte Hornets", aliases: ["cha", "hornets"] },
  { displayName: "Chicago Bulls", aliases: ["chi", "bulls"] },
  { displayName: "Cleveland Cavaliers", aliases: ["cle", "cavs", "cavaliers"] },
  { displayName: "Dallas Mavericks", aliases: ["dal", "mavs", "mavericks"] },
  { displayName: "Denver Nuggets", aliases: ["den", "nuggets"] },
  { displayName: "Detroit Pistons", aliases: ["det", "pistons"] },
  { displayName: "Golden State Warriors", aliases: ["gsw", "warriors", "golden state"] },
  { displayName: "Houston Rockets", aliases: ["hou", "rockets"] },
  { displayName: "Indiana Pacers", aliases: ["ind", "pacers"] },
  { displayName: "Los Angeles Clippers", aliases: ["lac", "la clippers", "clippers"] },
  { displayName: "Los Angeles Lakers", aliases: ["lal", "la lakers", "lakers"] },
  { displayName: "Memphis Grizzlies", aliases: ["mem", "grizzlies"] },
  { displayName: "Miami Heat", aliases: ["mia", "heat"] },
  { displayName: "Milwaukee Bucks", aliases: ["mil", "bucks"] },
  { displayName: "Minnesota Timberwolves", aliases: ["min", "wolves", "timberwolves"] },
  { displayName: "New Orleans Pelicans", aliases: ["nop", "pelicans"] },
  { displayName: "New York Knicks", aliases: ["nyk", "knicks"] },
  { displayName: "Oklahoma City Thunder", aliases: ["okc", "oklahoma city", "thunder"] },
  { displayName: "Orlando Magic", aliases: ["orl", "magic"] },
  { displayName: "Philadelphia 76ers", aliases: ["phi", "sixers", "76ers"] },
  { displayName: "Phoenix Suns", aliases: ["phx", "suns"] },
  { displayName: "Portland Trail Blazers", aliases: ["por", "blazers", "trail blazers"] },
  { displayName: "Sacramento Kings", aliases: ["sac", "kings"] },
  { displayName: "San Antonio Spurs", aliases: ["sas", "spurs"] },
  { displayName: "Toronto Raptors", aliases: ["tor", "raptors"] },
  { displayName: "Utah Jazz", aliases: ["uta", "jazz"] },
  { displayName: "Washington Wizards", aliases: ["was", "wizards"] },
  { displayName: "Arizona Diamondbacks", aliases: ["ari", "dbacks", "diamondbacks"] },
  { displayName: "Atlanta Braves", aliases: ["atl", "braves"] },
  { displayName: "Baltimore Orioles", aliases: ["bal", "orioles"] },
  { displayName: "Boston Red Sox", aliases: ["bos", "red sox"] },
  { displayName: "Chicago Cubs", aliases: ["chc", "cubs"] },
  { displayName: "Chicago White Sox", aliases: ["cws", "white sox"] },
  { displayName: "Cincinnati Reds", aliases: ["cin", "reds"] },
  { displayName: "Cleveland Guardians", aliases: ["cle", "guardians"] },
  { displayName: "Colorado Rockies", aliases: ["col", "rockies"] },
  { displayName: "Detroit Tigers", aliases: ["det", "tigers"] },
  { displayName: "Houston Astros", aliases: ["hou", "astros"] },
  { displayName: "Kansas City Royals", aliases: ["kc", "royals"] },
  { displayName: "Los Angeles Angels", aliases: ["laa", "angels"] },
  { displayName: "Los Angeles Dodgers", aliases: ["lad", "dodgers"] },
  { displayName: "Miami Marlins", aliases: ["mia", "marlins"] },
  { displayName: "Milwaukee Brewers", aliases: ["mil", "brewers"] },
  { displayName: "Minnesota Twins", aliases: ["min", "twins"] },
  { displayName: "New York Mets", aliases: ["nym", "mets"] },
  { displayName: "New York Yankees", aliases: ["nyy", "yankees"] },
  { displayName: "Oakland Athletics", aliases: ["ath", "athletics"] },
  { displayName: "Philadelphia Phillies", aliases: ["phi", "phillies"] },
  { displayName: "Pittsburgh Pirates", aliases: ["pit", "pirates"] },
  { displayName: "San Diego Padres", aliases: ["sd", "padres"] },
  { displayName: "San Francisco Giants", aliases: ["sf", "giants"] },
  { displayName: "Seattle Mariners", aliases: ["sea", "mariners"] },
  { displayName: "St. Louis Cardinals", aliases: ["stl", "cardinals", "st louis"] },
  { displayName: "Tampa Bay Rays", aliases: ["tb", "rays"] },
  { displayName: "Texas Rangers", aliases: ["tex", "rangers"] },
  { displayName: "Toronto Blue Jays", aliases: ["tor", "blue jays"] },
  { displayName: "Washington Nationals", aliases: ["wsh", "nationals", "nats"] },
  { displayName: "Duke Blue Devils", aliases: ["duke", "blue devils"] },
  { displayName: "North Carolina Tar Heels", aliases: ["unc", "north carolina", "tar heels"] },
  { displayName: "UConn Huskies", aliases: ["uconn", "huskies", "connecticut"] },
  { displayName: "St. John's Red Storm", aliases: ["st johns", "st johns red storm", "stj"] },
  { displayName: "Kansas Jayhawks", aliases: ["kansas", "jayhawks", "ku"] },
  { displayName: "High Point Panthers", aliases: ["high point", "panthers", "hpu"] },
  { displayName: "Wisconsin Badgers", aliases: ["wisconsin", "badgers", "wis"] },
];

function normalizeAliasText(value: string): string {
  return String(value || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[.\-_/]/g, " ")
    .replace(/[']/g, "")
    .replace(/[^a-z0-9\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function containsNormalizedPhrase(haystack: string, phrase: string): boolean {
  if (!phrase) return false;
  const paddedHaystack = ` ${haystack} `;
  const paddedPhrase = ` ${phrase} `;
  return paddedHaystack.includes(paddedPhrase);
}

function buildCanonicalKey(displayName: string): string {
  return normalizeAliasText(displayName);
}

const CANONICAL_TO_VARIANTS = new Map<string, Set<string>>();
const VARIANT_TO_CANONICAL = new Map<string, Set<string>>();
const CANONICAL_TO_DISPLAY = new Map<string, string>();

for (const entry of TEAM_ALIAS_ENTRIES) {
  const canonicalKey = buildCanonicalKey(entry.displayName);
  const variants = new Set<string>([canonicalKey]);

  for (const alias of entry.aliases) {
    const normalizedAlias = normalizeAliasText(alias);
    if (normalizedAlias) {
      variants.add(normalizedAlias);
    }
  }

  CANONICAL_TO_DISPLAY.set(canonicalKey, entry.displayName);
  CANONICAL_TO_VARIANTS.set(canonicalKey, variants);

  for (const variant of Array.from(variants)) {
    const existing = VARIANT_TO_CANONICAL.get(variant) ?? new Set<string>();
    existing.add(canonicalKey);
    VARIANT_TO_CANONICAL.set(variant, existing);
  }
}

export function normalizeTeamSearchQuery(value: string): string {
  return normalizeAliasText(value);
}

export function expandTeamAliasSearchQuery(rawQuery: string): string {
  const trimmed = rawQuery.trim();
  if (!trimmed) return "";

  const normalized = normalizeAliasText(trimmed);
  const canonicalKeys = VARIANT_TO_CANONICAL.get(normalized);
  if (!canonicalKeys || canonicalKeys.size !== 1) {
    return trimmed;
  }

  const canonicalKey = Array.from(canonicalKeys)[0];
  return CANONICAL_TO_DISPLAY.get(canonicalKey) ?? trimmed;
}

export function matchesTeamAliasSearch(rawQuery: string, haystackValues: Array<string | null | undefined>): boolean {
  const normalizedQuery = normalizeAliasText(rawQuery);
  if (!normalizedQuery) return true;

  const normalizedHaystack = normalizeAliasText(haystackValues.filter(Boolean).join(" "));
  if (!normalizedHaystack) return false;

  if (normalizedHaystack.includes(normalizedQuery)) {
    return true;
  }

  const canonicalKeys = VARIANT_TO_CANONICAL.get(normalizedQuery);
  if (!canonicalKeys || canonicalKeys.size === 0) {
    return false;
  }

  for (const canonicalKey of Array.from(canonicalKeys)) {
    const variants = CANONICAL_TO_VARIANTS.get(canonicalKey);
    if (!variants) continue;
    for (const variant of Array.from(variants)) {
      if (containsNormalizedPhrase(normalizedHaystack, variant)) {
        return true;
      }
    }
  }

  return false;
}