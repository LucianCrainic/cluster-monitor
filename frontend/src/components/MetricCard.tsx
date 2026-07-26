interface MetricCardProps {
  label: string;
  value: number;
  tone?: "default" | "positive" | "warning" | "danger" | "info";
  detail: string;
}

export function MetricCard({
  label,
  value,
  tone = "default",
  detail,
}: MetricCardProps) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <p className="metric-card__label">{label}</p>
      <p className="metric-card__value">{value.toLocaleString()}</p>
      <p className="metric-card__detail">{detail}</p>
    </article>
  );
}
