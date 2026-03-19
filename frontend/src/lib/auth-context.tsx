"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createClient } from "@/lib/supabase";
import type { User, Session } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";

interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  session: null,
  loading: true,
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const previousUserIdRef = useRef<string | null>(null);

  useEffect(() => {
    const supabase = createClient();

    const syncAuthState = (nextSession: Session | null) => {
      const nextUser = nextSession?.user ?? null;
      const nextUserId = nextUser?.id ?? null;

      // Prevent cross-account cache bleed when switching users.
      if (previousUserIdRef.current !== nextUserId) {
        queryClient.clear();
      }

      previousUserIdRef.current = nextUserId;
      setSession(nextSession);
      setUser(nextUser);
      setLoading(false);
    };

    supabase.auth.getSession().then(({ data: { session } }) => {
      syncAuthState(session);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      syncAuthState(nextSession);
    });

    // Dev-only: get token from console for testing API (e.g. scan-bets)
    if (typeof window !== "undefined" && process.env.NODE_ENV === "development") {
      (window as unknown as { getAuthToken?: () => Promise<string | null> }).getAuthToken = async () => {
        const { data } = await createClient().auth.getSession();
        return data.session?.access_token ?? null;
      };
    }

    return () => subscription.unsubscribe();
  }, [queryClient]);

  const signOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
  };

  return (
    <AuthContext.Provider value={{ user, session, loading, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
