// Formatação de números e horários no padrão brasileiro.
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("pt-BR");
const clock = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const price = (value) => decimal.format(Number(value ?? 0));
export const qty = (value) => integer.format(Number(value ?? 0));
export const time = (value) => clock.format(new Date(value));

export const signedPct = (value) => {
  const n = Number(value ?? 0);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${decimal.format(Math.abs(n))}%`;
};

export const tone = (value) => (Number(value) > 0 ? "up" : Number(value) < 0 ? "down" : "muted");

// Lê o id do usuário do próprio JWT (claim "sub"), sem validar: serve só para exibição.
export function userIdFromToken(token) {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return Number(JSON.parse(atob(payload)).sub);
  } catch {
    return null;
  }
}
