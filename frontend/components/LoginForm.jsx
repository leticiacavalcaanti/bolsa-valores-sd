"use client";
import { useState } from "react";
import { auth } from "../lib/api";
import Mark from "./Mark";

// Papéis cadastrados em db/init.sql.
const LISTED = [
  ["ARAC3", "Aracaju Energia", "Energia"],
  ["CAJU3", "Cajueiro Alimentos", "Alimentos"],
  ["FORR3", "Forró Entretenimento", "Entretenimento"],
  ["MANG3", "Mangue Biotecnologia", "Saúde"],
  ["SERT3", "Sertão Tech", "Tecnologia"],
];

export default function LoginForm({ onSignIn }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

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

  const switchTo = (next) => {
    setMode(next);
    setError("");
  };

  return (
    <main className="login">
      <section className="login-intro">
        <div className="brand"><Mark size={22} />Home Broker</div>
        <div>
          <h1>Pregão simulado</h1>
          <p className="lead">Ordens limitadas, livro de ofertas e carteira.</p>
        </div>
        <div className="board">
          <p className="board-title">Papéis negociados neste pregão</p>
          <ul>
            {LISTED.map(([symbol, name, sector]) => (
              <li key={symbol}>
                <strong>{symbol}</strong>
                <span>{name}</span>
                <span>{sector}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="tabs" role="tablist" aria-label="Acesso">
          <button type="button" role="tab" className="tab" aria-selected={isLogin} onClick={() => switchTo("login")}>
            Entrar
          </button>
          <button type="button" role="tab" className="tab" aria-selected={!isLogin} onClick={() => switchTo("register")}>
            Criar conta
          </button>
        </div>
        <div>
          <h2 id="login-title">{isLogin ? "Entre para negociar" : "Crie sua conta de investidor"}</h2>
          <p className="sub">
            {isLogin ? "Sua sessão fica salva neste navegador." : "Você entra no pregão assim que a conta é criada."}
          </p>
        </div>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="username">Usuário</label>
            <input id="username" className="input" value={username} autoComplete="username"
                   onChange={(e) => setUsername(e.target.value)} required autoFocus />
            <span className="hint">3 a 20 letras, números ou _</span>
          </div>
          <div className="field">
            <label htmlFor="password">Senha</label>
            <input id="password" className="input" type="password" value={password}
                   autoComplete={isLogin ? "current-password" : "new-password"}
                   onChange={(e) => setPassword(e.target.value)} required />
            <span className="hint">Mínimo de 6 caracteres</span>
          </div>
          {error && <p className="notice error" role="alert">{error}</p>}
          <button className="btn btn-primary" disabled={busy}>
            {busy ? "Aguarde..." : isLogin ? "Entrar" : "Cadastrar e entrar"}
          </button>
        </form>
        <p className="switch">
          {isLogin ? "Ainda não negocia aqui? " : "Já tem conta? "}
          <button type="button" className="text-action" onClick={() => switchTo(isLogin ? "register" : "login")}>
            {isLogin ? "Não tenho conta" : "Já tenho conta"}
          </button>
        </p>
      </section>
    </main>
  );
}
