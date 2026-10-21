// Marca do Home Broker: três níveis de um livro de ofertas.
export default function Mark({ size = 20 }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
      <rect x="2" y="3" width="10" height="3" fill="#4a8ad6" />
      <rect x="2" y="8.5" width="16" height="3" fill="#4a8ad6" />
      <rect x="2" y="14" width="6" height="3" fill="#4a8ad6" />
    </svg>
  );
}
