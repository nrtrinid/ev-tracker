import { NextResponse } from 'next/server';

/**
 * Sniper route: once backend is awake, trigger specific backend ops tasks.
 * Accepts `?target=...` and POSTs to ${BACKEND_BASE_URL}/api/ops/trigger/{target}
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const targetParam = url.searchParams.get('target') ?? '';
  const backendBaseUrl = process.env.BACKEND_BASE_URL;

  const authHeader = request.headers.get('authorization') ?? '';
  const cronSecret = process.env.CRON_SECRET;

  if (!cronSecret) {
    return NextResponse.json({ error: 'CRON_SECRET not configured' }, { status: 500 });
  }
  const expected = `Bearer ${cronSecret}`;
  if (authHeader !== expected) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  if (!targetParam) {
    return NextResponse.json({ error: 'Missing target parameter' }, { status: 400 });
  }
  if (!backendBaseUrl) {
    return NextResponse.json({ error: 'BACKEND_BASE_URL not configured' }, { status: 500 });
  }

  // Keep the public query parameter stable, but map to backend route names.
  const target =
    targetParam === 'settle'
      ? 'auto-settle'
      : targetParam;

  // Only allow known ops targets so this route can't be used as a generic backend proxy.
  const allowedTargets = new Set(['board-refresh', 'auto-settle', 'test-discord']);
  if (!allowedTargets.has(target)) {
    return NextResponse.json({ error: 'Invalid target' }, { status: 400 });
  }

  // The backend expects X-Ops-Token on ops routes. By default, reuse CRON_SECRET.
  // If you want separate secrets, set CRON_TOKEN on Vercel and on the backend as CRON_TOKEN.
  const backendCronToken = process.env.CRON_TOKEN ?? cronSecret;

  const endpoint = `${backendBaseUrl.replace(/\/$/, '')}/api/ops/trigger/${target}`;

  try {
    const requestInit = {
      method: 'POST',
      headers: {
        'accept': 'application/json',
        'content-type': 'application/json',
        'x-ops-token': backendCronToken,
      },
      body: JSON.stringify({}),
    } satisfies RequestInit;

    const resp = await fetch(endpoint, requestInit);

    let data: unknown = null;
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        data = await resp.json();
      } catch {
        // If JSON parsing fails, fall back to text
        const text = await resp.text();
        data = { text };
      }
    } else {
      const text = await resp.text();
      data = { text };
    }

    return NextResponse.json(data, { status: resp.status });
  } catch (error) {
    console.error('Trigger backend error:', error);
    return NextResponse.json({ error: 'Failed to trigger backend', target }, { status: 502 });
  }
}
