export function normalizeInviteCode(value: string | null | undefined): string {
  return (value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

export function betaInviteCodeEnabled(rawInviteCode: string | undefined): boolean {
  return normalizeInviteCode(rawInviteCode).length > 0;
}
