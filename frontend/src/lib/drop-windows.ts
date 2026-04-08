const PHOENIX_TZ = "America/Phoenix";

function getTimeZoneOffsetMs(date: Date, timeZone: string): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const parts = dtf.formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value;
  const year = Number(get("year"));
  const month = Number(get("month"));
  const day = Number(get("day"));
  const hour = Number(get("hour"));
  const minute = Number(get("minute"));
  const second = Number(get("second"));
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  return asUtc - date.getTime();
}

function zonedTimeToUtcMs(
  year: number,
  month1: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): number {
  const utcGuess = Date.UTC(year, month1 - 1, day, hour, minute, 0);
  const guessDate = new Date(utcGuess);
  const offset = getTimeZoneOffsetMs(guessDate, timeZone);
  return utcGuess - offset;
}

function formatLocalClock(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function getDailyDropWindowsLocal(now: Date = new Date()): {
  morningLocal: string;
  afternoonLocal: string;
  localLabel: string;
  mstLabel: string;
} {
  try {
    const dtf = new Intl.DateTimeFormat("en-US", {
      timeZone: PHOENIX_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    const parts = dtf.formatToParts(now);
    const get = (type: string) => parts.find((part) => part.type === type)?.value;
    const year = Number(get("year"));
    const month = Number(get("month"));
    const day = Number(get("day"));

    const morningUtcMs = zonedTimeToUtcMs(year, month, day, 10, 30, PHOENIX_TZ);
    const afternoonUtcMs = zonedTimeToUtcMs(year, month, day, 15, 30, PHOENIX_TZ);
    const morningLocal = formatLocalClock(new Date(morningUtcMs));
    const afternoonLocal = formatLocalClock(new Date(afternoonUtcMs));

    return {
      morningLocal,
      afternoonLocal,
      localLabel: `${morningLocal} and ${afternoonLocal} local time`,
      mstLabel: "10:30 AM and 3:30 PM MST",
    };
  } catch {
    return {
      morningLocal: "10:30 AM",
      afternoonLocal: "3:30 PM",
      localLabel: "10:30 AM and 3:30 PM local time",
      mstLabel: "10:30 AM and 3:30 PM MST",
    };
  }
}
