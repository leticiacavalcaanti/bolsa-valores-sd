"use client";
import { useCallback, useEffect, useState } from "react";
import Broker from "../components/Broker";
import LoginForm from "../components/LoginForm";

const STORAGE_KEY = "homebroker.session";

export default function Page() {
  const [session, setSession] = useState(null);
  const [ready, setReady] = useState(false);

  // Restaura a sessão após recarregar a página (reconhecimento do usuário).
  useEffect(() => {
    try {
      setSession(JSON.parse(localStorage.getItem(STORAGE_KEY)));
    } catch {
      setSession(null);
    }
    setReady(true);
  }, []);

  const signIn = (data) => {
    const value = { token: data.access_token, username: data.user.username };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    setSession(value);
  };

  const signOut = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setSession(null);
  }, []);

  if (!ready) return null;
  return session ? <Broker session={session} onSignOut={signOut} /> : <LoginForm onSignIn={signIn} />;
}
