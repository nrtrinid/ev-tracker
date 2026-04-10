import { NextResponse } from "next/server";

import {
  betaInviteCodeEnabled,
  normalizeInviteCode,
} from "@/lib/server/beta-access-utils";

type BetaAccessCheckRequest = {
  inviteCode?: string;
};

function configuredInviteCode(): string {
  return normalizeInviteCode(process.env.BETA_INVITE_CODE);
}

export async function GET() {
  return NextResponse.json(
    {
      ok: true,
      restricted: betaInviteCodeEnabled(process.env.BETA_INVITE_CODE),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

export async function POST(request: Request) {
  let payload: BetaAccessCheckRequest | null = null;
  try {
    payload = await request.json();
  } catch {
    payload = null;
  }

  const inviteCode = typeof payload?.inviteCode === "string" ? payload.inviteCode : "";
  const expectedInviteCode = configuredInviteCode();
  if (!expectedInviteCode) {
    return NextResponse.json(
      {
        ok: true,
        restricted: false,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  if (!inviteCode.trim()) {
    return NextResponse.json(
      { ok: false, error: "Invite code is required." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (normalizeInviteCode(inviteCode) !== expectedInviteCode) {
    return NextResponse.json(
      {
        ok: false,
        restricted: true,
        error: "That invite code is not valid.",
      },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }

  return NextResponse.json(
    {
      ok: true,
      restricted: true,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
