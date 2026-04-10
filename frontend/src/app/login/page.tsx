"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { sendAnalyticsEvent } from "@/lib/analytics";
import { grantBetaAccess } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function LoginPageContent() {
  const discordInviteUrl = process.env.NEXT_PUBLIC_DISCORD_INVITE_URL?.trim() || "";
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (searchParams.get("beta") === "restricted") {
      setError("This account still needs the beta invite code. Sign in, then enter the code once to continue.");
    }
  }, [searchParams]);

  const verifyBetaAccess = async (targetInviteCode: string) => {
    const response = await fetch("/api/beta-access", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ inviteCode: targetInviteCode }),
    });

    if (response.ok) {
      return;
    }

    const data = await response.json().catch(() => ({}));
    const message =
      typeof data?.error === "string" && data.error.trim().length > 0
        ? data.error
        : "That invite code is not valid.";
    throw new Error(message);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);

    const supabase = createClient();

    try {
      if (isSignUp) {
        await verifyBetaAccess(inviteCode);

        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        void sendAnalyticsEvent({
          eventName: "signup_completed",
          route: "/login",
          appArea: "auth",
          properties: {
            method: "email_password",
          },
        });

        if (data.session) {
          try {
            await grantBetaAccess(inviteCode, data.session.access_token);
          } catch (grantError) {
            await supabase.auth.signOut();
            throw grantError;
          }
          setMessage("Your beta account is ready. Redirecting to Markets...");
          router.push("/");
          router.refresh();
          return;
        }

        setMessage(
          "Account created. Check your email for the confirmation step, then sign in and enter the invite code once."
        );
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (error) throw error;
        router.push("/");
        router.refresh();
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "An unexpected error occurred";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-xl bg-[#2C2416] flex items-center justify-center shadow-md mb-3">
            <span className="text-[#FAF8F5] font-bold text-xl tracking-tight">
              EV
            </span>
          </div>
          <h1 className="text-xl font-semibold text-foreground">EV Tracker</h1>
          <span className="mt-2 inline-flex rounded-full border border-[#C4A35A]/35 bg-[#C4A35A]/12 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#6B5728]">
            Trusted beta
          </span>
          <p className="text-sm text-muted-foreground mt-1">
            {isSignUp ? "Create your beta account" : "Sign in to your beta account"}
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            {isSignUp
              ? "Ask your inviter for the beta code. You only need to redeem it once per account."
              : "If your account has not been approved yet, you will be asked for the beta code after sign-in."}
          </p>
          {discordInviteUrl && (
            <a
              href={discordInviteUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-2 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              Questions or bugs? Join the beta Discord.
            </a>
          )}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-3 bg-card p-6 rounded-lg border border-border shadow-soft">
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Email
              </label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-foreground mb-1.5"
              >
                Password
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                minLength={6}
                autoComplete={isSignUp ? "new-password" : "current-password"}
              />
            </div>

            {isSignUp && (
              <div>
                <label
                  htmlFor="inviteCode"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  Invite Code
                </label>
                <Input
                  id="inviteCode"
                  type="text"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  placeholder="Enter invite code"
                  required
                  autoComplete="one-time-code"
                />
              </div>
            )}

            {error && (
              <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-md">
                {error}
              </p>
            )}

            {message && (
              <p className="text-sm text-[#4A7C59] bg-[#4A7C59]/10 px-3 py-2 rounded-md">
                {message}
              </p>
            )}

            <Button type="submit" disabled={loading} className="w-full mt-1">
              {loading
                ? "..."
                : isSignUp
                  ? "Create Account"
                  : "Sign In"}
            </Button>
          </div>

          <p className="text-center text-sm text-muted-foreground">
            {isSignUp
              ? "Already have an account?"
              : "Don't have an account?"}{" "}
            <button
              type="button"
              onClick={() => {
                setIsSignUp(!isSignUp);
                setError("");
                setMessage("");
              }}
              className="text-foreground font-medium hover:text-primary transition-colors underline underline-offset-2"
            >
              {isSignUp ? "Sign in" : "Sign up"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageContent />
    </Suspense>
  );
}
