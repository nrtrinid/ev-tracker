import { NextResponse } from 'next/server';

/**
 * Sniper route: once Render is awake, trigger specific backend cron tasks.
 * Accepts `?target=...` and POSTs to https://ev-tracker-backend.onrender.com/api/cron/{target}
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const target = url.searchParams.get('target') ?? '';

  const authHeader = request.headers.get('authorization') ?? '';
  const cronSecret = process.env.CRON_SECRET;

  if (!cronSecret) {
    return NextResponse.json({ error: 'CRON_SECRET not configured' }, { status: 500 });
    }
  const expected = `Bearer ${cronSecret}`;
  if (authHeader !== expected) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  if (!target) {
    return NextResponse.json({ error: 'Missing target parameter' }, { status: 400 });
  }
  // Basic safeguard: only allow simple, safe path segments
  if (!/^[a-z0-9-]+$/.test(target)) {
    return NextResponse.json({ error: 'Invalid target' }, { status: 400 });
  }

  const endpoint = `https://ev-tracker-backend.onrender.com/api/cron/${target}`;

  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'accept': 'application/json',
        'content-type': 'application/json',
      },
      // Send empty JSON body; adjust if backend expects payload
      body: JSON.stringify({}),
    });

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
    return NextResponse.json({ error: 'Failed to trigger backend' }, { status: 502 });
  }
}

