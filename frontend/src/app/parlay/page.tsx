"use client";

import { useBettingPlatformStore } from "@/lib/betting-platform-store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { OnboardingBanner } from "@/components/OnboardingBanner";

export default function ParlayPage() {
  const { cart, removeCartLeg, clearCart } = useBettingPlatformStore();

  return (
    <main className="min-h-screen bg-background">
      <div className="container mx-auto max-w-2xl space-y-4 px-4 py-6 pb-24">
        <OnboardingBanner
          step="parlay_builder"
          title="Parlay cart is persistent"
          body="Add legs from either scanner surface and your cart will stay with you across routes and reloads on this browser."
        />
        <div>
          <h1 className="text-2xl font-semibold">Parlay Builder</h1>
          <p className="text-sm text-muted-foreground">
            Build a browser-local cart from straight bets and player props. Same-event combinations are blocked for now.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Cart</h2>
              {cart.length > 0 && (
                <Button variant="outline" size="sm" onClick={clearCart}>
                  Clear
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {cart.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Add legs from the scanner to start building a cross-surface parlay cart.
              </p>
            ) : (
              cart.map((leg) => (
                <div
                  key={leg.id}
                  className="flex items-start justify-between rounded-lg border border-border bg-background px-3 py-3"
                >
                  <div>
                    <p className="text-sm font-semibold">{leg.display}</p>
                    <p className="text-xs text-muted-foreground">
                      {leg.surface === "player_props" ? "Player Props" : "Straight Bets"} • {leg.sportsbook} • {leg.event}
                    </p>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => removeCartLeg(leg.id)}>
                    Remove
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
