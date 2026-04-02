"use client";

import { ExternalLink, MessageSquare, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const DISCORD_INVITE_URL = process.env.NEXT_PUBLIC_DISCORD_INVITE_URL?.trim() || "";

type TrustedBetaCardProps = {
  className?: string;
  compact?: boolean;
};

export function TrustedBetaCard({ className, compact = false }: TrustedBetaCardProps) {
  const hasInvite = DISCORD_INVITE_URL.length > 0;

  return (
    <Card
      className={cn(
        "border-[#C4A35A]/35 bg-[linear-gradient(135deg,rgba(250,245,232,0.92),rgba(255,255,255,0.98))]",
        className,
      )}
    >
      <CardHeader className={compact ? "pb-2" : "pb-3"}>
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#2C2416] text-[#FAF8F5] shadow-sm">
            <ShieldCheck className="h-4.5 w-4.5" />
          </div>
          <div className="space-y-1">
            <div className="inline-flex items-center rounded-full border border-[#C4A35A]/35 bg-[#C4A35A]/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#6B5728]">
              Trusted Beta
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">Feedback lives in Discord</h2>
              <p className="text-xs text-muted-foreground">
                This build is for invited testers. Bug reports, product confusion, and quick reactions all go through the beta Discord.
              </p>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className={cn("space-y-3", compact && "pt-0")}>
        <div className="rounded-lg border border-[#C4A35A]/25 bg-background/70 px-3 py-2 text-xs text-muted-foreground">
          Market coverage, CLV capture, and board composition will keep evolving during beta, so fast feedback is especially helpful.
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {hasInvite ? (
            <Button asChild size="sm">
              <a href={DISCORD_INVITE_URL} target="_blank" rel="noreferrer">
                <MessageSquare className="mr-1.5 h-4 w-4" />
                Join Beta Discord
                <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
              </a>
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Discord invites are shared directly with beta testers by the person who sent the app link.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
