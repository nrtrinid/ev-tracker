import { NextResponse } from 'next/server';

/**
 * Alarm Clock route: wakes backend by pinging /health and aborting after 9s.
 * Returns a degraded status if backend is unreachable so failures are visible.
 */
export async function GET(request: Request) {
  const authHeader = request.headers.get('authorization') ?? '';
  const cronSecret = process.env.CRON_SECRET;
  const backendBaseUrl = process.env.BACKEND_BASE_URL;

  if (!cronSecret) {
    return NextResponse.json({ error: 'CRON_SECRET not configured' }, { status: 500 });
  }
  if (!backendBaseUrl) {
    return NextResponse.json({ error: 'BACKEND_BASE_URL not configured' }, { status: 500 });
  }
  const expected = `Bearer ${cronSecret}`;
  if (authHeader !== expected) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 9000);
  const endpoint = `${backendBaseUrl.replace(/\/$/, '')}/health`;
  let status = 502;
  let body: unknown = null;

  try {
    const resp = await fetch(endpoint, {
      method: 'GET',
      signal: controller.signal,
    });
    status = resp.status;
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      body = await resp.json().catch(() => null);
    } else {
      body = await resp.text().catch(() => null);
    }
  } catch (error: unknown) {
    // Ignore the intentional abort; log other errors for observability.
    if (!(error instanceof Error && error.name === 'AbortError')) {
      console.error('Wakeup ping error:', error);
    }
  } finally {
    clearTimeout(timeoutId);
  }

  const ok = status >= 200 && status < 300;
  return NextResponse.json(
    {
      ok,
      backend_status: status,
      backend_health: body,
    },
    { status: ok ? 200 : 502 }
  );
}

