// Cliente HTTP das APIs (auth-service e market-service).
export const AUTH_URL = process.env.NEXT_PUBLIC_AUTH_URL || "http://localhost:8001";
export const MARKET_URL = process.env.NEXT_PUBLIC_MARKET_URL || "http://localhost:8002";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(base, path, { method = "GET", body, token } = {}) {
  let response;
  try {
    response = await fetch(`${base}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Servidor indisponível. Tente novamente.", 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // 422 do FastAPI (validação) traz uma lista em "detail".
    const detail = Array.isArray(data.detail) ? "Dados inválidos" : data.detail;
    throw new ApiError(detail || "Erro inesperado", response.status);
  }
  return data;
}

export const auth = {
  register: (username, password) => request(AUTH_URL, "/register", { method: "POST", body: { username, password } }),
  login: (username, password) => request(AUTH_URL, "/login", { method: "POST", body: { username, password } }),
};

export const market = {
  assets: (token) => request(MARKET_URL, "/assets", { token }),
  book: (token, symbol) => request(MARKET_URL, `/book/${symbol}`, { token }),
  portfolio: (token) => request(MARKET_URL, "/portfolio", { token }),
  orders: (token) => request(MARKET_URL, "/orders", { token }),
  trades: (token) => request(MARKET_URL, "/trades", { token }),
  placeOrder: (token, order) => request(MARKET_URL, "/orders", { method: "POST", body: order, token }),
  cancelOrder: (token, id) => request(MARKET_URL, `/orders/${id}`, { method: "DELETE", token }),
};

export const brl = (value) =>
  Number(value ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
