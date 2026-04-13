"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { grantBetaAccess } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function BetaAccessPage() {
  const router = useRouter();
  const { user, signOut, loading } = useAuth();
  const discordInviteUrl = process.env.NEXT_PUBLIC_DISCORD_INVITE_URL?.trim() || "";
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSignOut = async () => {
    await signOut();
    router.push("/login?beta=restricted");
    router.refresh();
  };

  const handleGrantAccess = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) {
      setError("Sign in first, then enter the beta invite code.");
      return;
    }

    setError("");
    setSubmitting(true);
    try {
      await grantBetaAccess(inviteCode);
      router.push("/");
      router.refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unable to verify that invite code.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-soft">
        <span className="inline-flex rounded-full border border-primary/35 bg-primary/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
          Trusted beta
        </span>
        <h1 className="mt-3 text-xl font-semibold text-foreground">Enter Beta Code</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This build is limited to invited testers. Enter the shared beta code once and this account will stay approved for future sign-ins.
        </p>
        {user?.email ? (
          <p className="mt-3 rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            Signed in as <span className="font-medium text-foreground">{user.email}</span>
          </p>
        ) : null}
        <form className="mt-5 space-y-3" onSubmit={handleGrantAccess}>
          <div>
            <label
              htmlFor="betaInviteCode"
              className="block text-sm font-medium text-foreground mb-1.5"
            >
              Invite Code
            </label>
            <Input
              id="betaInviteCode"
              type="text"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              placeholder="Enter invite code"
              required
              autoComplete="one-time-code"
            />
          </div>
          {error ? (
            <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-md">
              {error}
            </p>
          ) : null}
          <Button type="submit" className="w-full" disabled={submitting || loading || !user}>
            {submitting ? "Checking..." : "Unlock Beta Access"}
          </Button>
        </form>
        <div className="mt-3 space-y-2">
          {!user ? (
            <Button className="w-full" asChild>
              <Link href="/login?beta=restricted">Back to Login</Link>
            </Button>
          ) : null}
          {user ? (
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={handleSignOut}
              disabled={loading}
            >
              Sign Out And Try Another Email
            </Button>
          ) : null}
          {discordInviteUrl ? (
            <Button variant="outline" className="w-full" asChild>
              <a href={discordInviteUrl} target="_blank" rel="noreferrer">
                Open Beta Discord
              </a>
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
