"use client";
// Mantém o estado de mercado em tempo real via WebSocket, com reconexão automática.
import { useCallback, useEffect, useRef, useState } from "react";
import { MARKET_URL, market } from "./api";

const WS_URL = MARKET_URL.replace(/^http/, "ws") + "/ws";
const MAX_BACKOFF_MS = 10000;

export function useMarket(token, symbol, onAuthError) {
  const [connected, setConnected] = useState(false);
  const [assets, setAssets] = useState([]);
  const [book, setBook] = useState({ bids: [], asks: [] });
  const [online, setOnline] = useState([]);
  const [feed, setFeed] = useState([]);
  // Incrementa quando algo do usuário muda (ordem/negociação): quem usa refaz as consultas.
  const [version, setVersion] = useState(0);
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  const refreshBook = useCallback(async () => {
    try {
      setBook(await market.book(token, symbolRef.current));
    } catch (err) {
      if (err.status === 401) onAuthError?.();
    }
  }, [token, onAuthError]);

  useEffect(() => {
    refreshBook();
  }, [symbol, refreshBook]);

  useEffect(() => {
    let socket;
    let retryTimer;
    let attempt = 0;
    let closedByUs = false;

    const addToFeed = (text) => setFeed((old) => [{ id: Date.now() + Math.random(), text }, ...old].slice(0, 30));

    const connect = () => {
      socket = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
        setVersion((v) => v + 1); // ressincroniza o que foi perdido durante a queda
        refreshBook();
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "snapshot") setAssets(msg.assets);
        if (msg.type === "presence") setOnline(msg.users);
        if (msg.type === "price_update") {
          setAssets((old) => old.map((a) => (a.symbol === msg.symbol ? { ...a, ...msg } : a)));
        }
        if (msg.type === "book_update" && msg.symbol === symbolRef.current) setBook(msg);
        if (msg.type === "trade") addToFeed(`${msg.symbol}: ${msg.quantity} @ ${Number(msg.price).toFixed(2)}`);
        if (msg.type === "order_update") {
          addToFeed(`Ordem #${msg.order.id} ${msg.order.symbol}: ${msg.order.status}`);
          setVersion((v) => v + 1);
        }
      };
      socket.onclose = (event) => {
        setConnected(false);
        if (event.code === 4401) return onAuthError?.(); // token inválido: não adianta reconectar
        if (closedByUs) return;
        // Backoff exponencial: 1s, 2s, 4s... até 10s.
        const delay = Math.min(1000 * 2 ** attempt++, MAX_BACKOFF_MS);
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closedByUs = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [token, onAuthError, refreshBook]);

  return { connected, assets, book, online, feed, version };
}
