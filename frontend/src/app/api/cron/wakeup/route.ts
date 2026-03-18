import { NextResponse } from 'next/server';

/**
 * Alarm Clock route: wakes Render by pinging /health and aborting after 9s.
 * Always returns 200 quickly to avoid Vercel's 10s hard timeout counting as failure.
 */
export async function GET(request: Request) {
  const authHeader = request.headers.get('authorization') ?? '';
  const cronSecret = process.env.CRON_SECRET;

  if (!cronSecret) {
    return NextResponse.json({ error: 'CRON_SECRET not configured' }, { status: 500 });
  }
  const expected = `Bearer ${cronSecret}`;
  if (authHeader !== expected) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 9000);

  try {
    await fetch('https://ev-tracker-backend.onrender.com/health', {
      method: 'GET',
      signal: controller.signal,
    });
  } catch (error: unknown) {
    // Ignore the intentional abort; log other errors for observability.
    if (!(error instanceof Error && error.name === 'AbortError')) {
      // Non-fatal: we still return 200 to ensure the cron is considered successful.
      console.error('Wakeup ping error:', error);
    }
  } finally {
    clearTimeout(timeoutId);
  }

  return NextResponse.json({ ok: true });
}

