const MULTI_WORD_NICKNAMES = new Set([
  "trail blazers",
  "red sox",
  "white sox",
  "blue jays",
  "red storm",
  "tar heels",
  "blue devils",
  "golden knights",
]);

function extractNickname(teamName: string): string {
  const cleaned = String(teamName || "").trim().replace(/\s+/g, " ");
  if (!cleaned) return "";

  const parts = cleaned.split(" ");
  if (parts.length === 1) return parts[0];

  const last = parts[parts.length - 1];
  const prev = parts[parts.length - 2];
  const pair = `${prev} ${last}`.toLowerCase();

  if (MULTI_WORD_NICKNAMES.has(pair)) return `${prev} ${last}`;
  return last;
}

function splitMatchup(eventLabel: string): [string, string] | null {
  const normalized = eventLabel
    .replace(/\s+vs\.?\s+/i, " @ ")
    .replace(/\s+v\.?\s+/i, " @ ")
    .trim();

  const parts = normalized.split(/\s+@\s+/);
  if (parts.length !== 2) return null;

  const away = parts[0]?.trim();
  const home = parts[1]?.trim();
  if (!away || !home) return null;

  return [away, home];
}

export function buildEventNicknameLabel(eventLabel: string | null | undefined): string {
  const raw = String(eventLabel || "").trim();
  if (!raw) return "";

  const matchup = splitMatchup(raw);
  if (!matchup) return raw;

  const [away, home] = matchup;
  const awayNickname = extractNickname(away);
  const homeNickname = extractNickname(home);
  if (!awayNickname || !homeNickname) return raw;

  return `${awayNickname} @ ${homeNickname}`;
}