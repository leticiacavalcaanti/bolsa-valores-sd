"use client";
import { useState } from "react";
import { auth } from "../lib/api";

export default function LoginForm({ onSignIn }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "register") await auth.register(username, password);
      onSignIn(await auth.login(username, password));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <form className="card" onSubmit={submit}>
        <h1>Home Broker</h1>
        <p className="muted">{mode === "login" ? "Entre para negociar" : "Crie sua conta de investidor"}</p>
        <input placeholder="Usuário (3-20 letras, números ou _)" value={username}
               onChange={(e) => setUsername(e.target.value)} required autoFocus />
        <input type="password" placeholder="Senha (mín. 6 caracteres)" value={password}
               onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="error">{error}</p>}
        <button disabled={busy}>{mode === "login" ? "Entrar" : "Cadastrar e entrar"}</button>
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Não tenho conta" : "Já tenho conta"}
        </button>
      </form>
    </main>
  );
}
