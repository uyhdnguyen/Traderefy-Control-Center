import { Children } from 'react';

// Shared presentational pieces for the dark redesign. Display only: no data
// fetching and no metric definitions live here. Pages pass values they already
// compute, so every calculation stays exactly where it was.

export function PageHeader({ title, subtitle, actions, children }) {
  return (
    <div className="page-header">
      <div style={{ minWidth: 0 }}>
        <h1 className="page-title">{title}</h1>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
        {children}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function PanelHead({ title, sub, right }) {
  return (
    <div className="panel-head">
      <div style={{ minWidth: 0 }}>
        <h2 className="section-title">{title}</h2>
        {sub && <div className="section-sub">{sub}</div>}
      </div>
      {right}
    </div>
  );
}

/** Column count follows the number of cells so wrapped rows split evenly (8 -> 4+4, 7 -> 4+3). */
export function KpiStrip({ children, style, label }) {
  const count = Children.toArray(children).length;
  return <section className="kpi-strip" data-cols={count} style={style} aria-label={label}>{children}</section>;
}

/** One metric in a KPI strip. `tone` colours the value: pos | neg | caution | undefined. */
export function KpiCell({ label, value, tone, foot, children, title }) {
  const cls = tone === 'pos' ? 'pos' : tone === 'neg' ? 'neg' : tone === 'caution' ? 'caution' : '';
  return (
    <div className="kpi-cell" title={title}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${cls}`}>{value}</div>
      {foot && <div className="kpi-foot">{foot}</div>}
      {children}
    </div>
  );
}

/** Same goal logic as the original GoalBar: progress = value / goal, capped at 100%. */
export function GoalMeter({ value, goal, label }) {
  if (goal == null) return null;
  const pct = Math.min((Number(value || 0) / Number(goal)) * 100, 100);
  const hit = Number(value || 0) >= Number(goal);
  return (
    <div className="kpi-goal">
      <div className="kpi-goal-row">
        <span className={hit ? 'met' : undefined}>{hit ? '✓ Goal met' : `${Math.round(pct)}% of goal`}</span>
        <span>Goal {label}</span>
      </div>
      <div className="meter" role="img" aria-label={hit ? `Goal ${label} met` : `${Math.round(pct)}% of goal ${label}`}>
        <span className={hit ? 'met' : undefined} style={{ width: `${Math.max(pct, 0)}%` }} />
      </div>
    </div>
  );
}

/** Previous-period comparison line. Identical thresholds and formats to the originals. */
export function DeltaLine({ curr, prev, type = 'number', neutral = false }) {
  if (prev == null || curr == null) return null;
  const delta = Number(curr) - Number(prev);
  if (Math.abs(delta) < 0.001) return null;
  const up = delta > 0;
  let label;
  if (type === 'percent') {
    label = `${up ? '↑ +' : '↓ '}${Math.abs(delta).toFixed(1)} pp`;
  } else if (type === 'currency') {
    const abs = Math.abs(delta);
    label = (up ? '↑ +$' : '↓ -$') + (abs >= 1000 ? `${(abs / 1000).toFixed(1)}K` : Math.round(abs).toString());
  } else if (type === 'integer') {
    label = `${up ? '↑ +' : '↓ '}${Math.abs(delta).toFixed(0)}`;
  } else {
    label = `${up ? '↑ +' : '↓ '}${Math.abs(delta).toFixed(2)}`;
  }
  const cls = neutral ? 'text-purple' : up ? 'pos' : 'neg';
  return <div className={`kpi-delta ${cls}`}>{label} vs prev</div>;
}

/** "+$1,234.56" / "-$1,234.56" with the sign always explicit. */
export function signedMoney(v, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${n < 0 ? '-' : '+'}$${abs}`;
}

/** Big money value with de-emphasised cents, sign explicit. */
export function MoneyValue({ value }) {
  const n = Number(value || 0);
  const abs = Math.abs(n);
  const dollars = Math.floor(abs).toLocaleString('en-US');
  const cents = abs.toFixed(2).split('.')[1];
  return (
    <span className="num">
      {n < 0 ? '-' : '+'}${dollars}<span className="kpi-cents">.{cents}</span>
    </span>
  );
}

export const toneOf = (n) => (n == null ? undefined : Number(n) > 0 ? 'pos' : Number(n) < 0 ? 'neg' : undefined);
