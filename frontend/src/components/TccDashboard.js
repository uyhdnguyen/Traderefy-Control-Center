import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Copy, RefreshCw } from 'lucide-react';
import { tccApi } from '../api';
import TusJournal from './TusJournal';
import './control-workspace.css';

// R10 Dashboard: one screen, three markets. Every value shown comes from a file a
// NinjaTrader engine wrote (see backend/nt_telemetry.py). Nothing here sends orders.

const STATE_CLASS = { live: 'positive', stale: 'warning', partial: 'warning', missing: 'negative',
  no_charts: 'neutral', clock_skew: 'warning', no_ninjatrader_folder: 'negative', default: 'neutral', read: 'positive' };
const STATE_LABEL = { live: 'Live', stale: 'Stale', partial: 'Partial', missing: 'Not found', no_charts: 'No charts',
  clock_skew: 'Clock skew', no_ninjatrader_folder: 'NT folder not found' };
const STAGE_CLASS = { sent_to_tem: 'positive', rejected: 'negative', expired: 'neutral', cancelled: 'neutral',
  approval_pending: 'warning', detected: 'neutral' };
const STAGE_LABEL = { sent_to_tem: 'Sent to TEM', rejected: 'Rejected', expired: 'Expired', cancelled: 'Cancelled',
  approval_pending: 'Approval pending', detected: 'Detected' };

export const age = s => {
  if (s == null || !Number.isFinite(s)) return '—';
  const a = Math.max(0, s);
  if (a < 90) return `${Math.round(a)}s`;
  if (a < 5400) return `${Math.round(a / 60)}m`;
  if (a < 172800) return `${Math.round(a / 3600)}h`;
  return `${Math.round(a / 86400)}d`;
};
const price = v => (typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—');
const money = v => (typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : '—');
const clock = iso => { if (!iso) return '—'; const d = new Date(iso); return Number.isNaN(d.getTime()) ? String(iso).slice(11, 19) : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };

function Chip({ state, label, title }) {
  return <span className={'cw-status ' + (STATE_CLASS[state] || 'neutral')} title={title}>{label || STATE_LABEL[state] || state || 'No data'}</span>;
}
function Panel({ title, extra, children, className = '' }) {
  return <section className={'cw-panel ' + className}><header className="cw-panel-head"><strong>{title}</strong>{extra}</header>{children}</section>;
}
function Empty({ label, detail }) {
  return <div className="cw-empty"><Activity size={25} /><strong>{label}</strong>{detail && <small>{detail}</small>}</div>;
}
function Trend({ value }) {
  if (value === 1) return <strong className="cw-green">▲ Bull</strong>;
  if (value === -1) return <strong className="cw-red">▼ Bear</strong>;
  if (value === 0) return <strong className="cw-muted">■ Flat</strong>;
  return <strong className="cw-muted">—</strong>;
}

function EngineRow({ name, engine, detail }) {
  return <div className="cw-engine">
    <span>{name}</span>
    <span className="cw-inline" style={{ alignItems: 'center' }}>
      {detail && <small className="cw-muted">{detail}</small>}
      <Chip state={engine?.state} title={engine?.evidence} label={engine?.state === 'live' || engine?.state === 'stale' ? `${STATE_LABEL[engine.state]} · ${age(engine.age_seconds)}` : undefined} />
    </span>
  </div>;
}

function MarketPanel({ m, session }) {
  if (!m) return null;
  const title = `${m.family}${m.root && m.root !== m.family ? ' (' + m.root + ')' : ''} · ${m.instrument || 'not running'}`;
  if (!m.root) {
    return <Panel title={title} extra={<Chip state={m.state} />}>
      <Empty label="No TUS / TEE publication" detail={m.detail || 'Open the M5 TUS and 699-tick TEE charts for this market.'} />
    </Panel>;
  }
  const lv = m.levels || {};
  const items = lv.items || [];
  const byName = Object.fromEntries(items.filter(i => i.source === 'AUTO').map(i => [i.name.toUpperCase(), i.price]));
  const tem = m.engines?.tem || {};
  const stale = m.engines?.tus_m5?.state === 'stale';
  return <Panel title={title} extra={<Chip state={m.state} />}>
    <div className="cw-engine-list">
      <EngineRow name="TUS · M5" engine={m.engines?.tus_m5} />
      <EngineRow name="TEE · 699 tick" engine={m.engines?.tee_699} detail={m.engines?.tee_699?.bar != null ? `bar ${m.engines.tee_699.bar}` : null} />
      <div className="cw-engine"><span>TEM · Execution</span>
        <Chip state={tem.state} title={tem.evidence} label={tem.state === 'missing' ? 'Not running' : `${tem.live_instances}/${tem.instances} live`} /></div>
    </div>
    {stale && <p className="cw-muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
      {session?.open ? 'TUS has not published recently — check the M5 chart is open and connected.' : 'Market closed — stale publication is expected.'}</p>}
    <div className="cw-trend tcc-trend4" style={{ marginTop: 12 }}>
      {[['Overall', 'overall'], ['PP', 'pp'], ['M15', 'm15'], ['M60', 'm60']].map(([label, key]) =>
        <div key={key}><small className="cw-muted">{label}</small><Trend value={m.trend?.[key]} /></div>)}
    </div>
    <table className="cw-table tcc-levels" style={{ marginTop: 10 }}><tbody>
      <tr><th>ORB H / L</th><td>{price(lv.orb?.high)} / {price(lv.orb?.low)}</td><th>PDH / PDL</th><td>{price(byName.PDH)} / {price(byName.PDL)}</td></tr>
      <tr><th>PP</th><td>{price(byName.PP)}</td><th>R1 / S1</th><td>{price(byName.R1)} / {price(byName.S1)}</td></tr>
      <tr><th>PDC</th><td>{price(byName.PDC)}</td><th>Key levels</th><td title={(lv.manual || []).map(price).join(', ')}>{(lv.manual || []).length ? (lv.manual || []).map(price).join(' · ') : 'none drawn'}</td></tr>
    </tbody></table>
    {(m.positions || []).map(p => <div key={p.account} className="cw-warning" style={{ margin: '10px 0 0' }}>
      Open {p.side} {Math.abs(p.quantity)} · {p.account} · avg {price(p.average_price)} · since {clock(p.opened)}</div>)}
  </Panel>;
}

function SetupsPanel({ markets }) {
  const rows = useMemo(() => {
    const out = [];
    (markets || []).forEach(m => {
      (m.setups?.signals || []).forEach(s => out.push({ ...s, market: m.root, kind: 'signal' }));
      (m.setups?.candidates || []).forEach(c => out.push({ time: c.time, family: 'FTR', market: m.root, direction: c.direction,
        entry: c.entry, stop: c.swing, tp1: c.tp1, tp2: c.tp2, status: c.status, stage: 'detected', source: c.source, kind: 'candidate' }));
    });
    const seen = new Set();
    return out.sort((a, b) => String(b.time).localeCompare(String(a.time)))
      .filter(r => { const k = [r.kind, r.market, r.family, r.direction, r.entry, r.status, String(r.time).slice(0, 16)].join('|'); if (seen.has(k)) return false; seen.add(k); return true; })
      .slice(0, 10);
  }, [markets]);
  return <Panel title="Setups · Signal routing" extra={<small className="cw-muted">TUS signal journal · TEE candidates</small>}>
    {rows.length ? <div className="cw-table-scroll"><table className="cw-table"><thead><tr>
      {['Time', 'Setup', 'Dir', 'Entry', 'Status'].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>
      {rows.map((r, i) => <tr key={i} title={`${r.source} · ${r.market} · stop ${price(r.stop)} · TP1 ${price(r.tp1)} · TP2 ${price(r.tp2)} · ${r.status || ''}`}>
        <td>{clock(r.time)}</td><td>{r.market} {r.family}{r.kind === 'candidate' ? ' cand.' : ''}</td><td>{r.direction === 'LONG' ? 'L' : r.direction === 'SHORT' ? 'S' : r.direction}</td>
        <td>{price(r.entry)}</td>
        <td><span className={'cw-status ' + (STAGE_CLASS[r.stage] || 'neutral')}>{STAGE_LABEL[r.stage] || r.stage}</span></td></tr>)}
    </tbody></table></div> : <Empty label="No setups recorded yet" detail="Signals appear when TUS writes its signal journal." />}
    <p className="cw-muted" style={{ fontSize: 12, margin: '8px 0 0' }}>TCC approval of setups is not enabled in this release; TUS routes to TEM exactly as before.</p>
  </Panel>;
}

function ExecutionPanel({ markets, shared }) {
  const instances = (markets || []).flatMap(m => (m.tem || []).map(t => ({ ...t, market: m.root })));
  const positions = (markets || []).flatMap(m => m.positions || []);
  const events = instances.flatMap(t => (t.events || []).map(e => ({ ...e, account: t.account, market: t.market })))
    .sort((a, b) => String(b.time).localeCompare(String(a.time))).slice(0, 8);
  return <Panel title="Active trades · Orders · TEM">
    {positions.length ? positions.map(p => <div key={p.account + p.instrument} className="cw-engine"><span>{p.account} · {p.instrument}</span>
      <strong className={p.side === 'LONG' ? 'cw-green' : 'cw-red'}>{p.side} {Math.abs(p.quantity)} @ {price(p.average_price)}</strong></div>)
      : <p className="cw-muted" style={{ marginTop: 0 }}>No open position in the TUS execution ledger.</p>}
    <div className="cw-table-scroll"><table className="cw-table"><thead><tr>{['TEM', 'Heartbeat', 'Last event'].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>
      {instances.map(t => <tr key={t.key}><td>{t.account}{t.family && !t.account.includes(t.family) ? ' · ' + t.family : ''}</td>
        <td><Chip state={t.heartbeat?.state} label={`${STATE_LABEL[t.heartbeat?.state] || '—'} · ${age(t.heartbeat?.age_seconds)}`} /></td>
        <td title={[t.last_diagnostic?.detail, t.order_status ? 'Order: ' + t.order_status.status + ' ' + t.order_status.detail : ''].filter(Boolean).join(' | ')}
          style={{ whiteSpace: 'normal' }}>{t.last_diagnostic ? `${t.last_diagnostic.code} · ${age(t.last_diagnostic.age_seconds)} ago` : '—'}
          {t.order_status && <div className="cw-muted" style={{ fontSize: 12 }}>Order: {t.order_status.status} · {age(t.order_status.age_seconds)} ago</div>}</td></tr>)}
      {!instances.length && <tr><td colSpan="3" className="cw-table-empty">No TEM instance found for the running charts.</td></tr>}
    </tbody></table></div>
    {shared && <p className="cw-muted" style={{ fontSize: 12 }} title={shared.note}>Last order update (any TEM): {shared.account} · {shared.status} · {age(shared.age_seconds)} ago</p>}
    {events.length > 0 && <details><summary className="cw-muted" style={{ cursor: 'pointer' }}>Recent TEM events ({events.length})</summary>
      <table className="cw-table"><tbody>{events.map((e, i) => <tr key={i} title={e.detail}><td>{clock(e.time)}</td><td>{e.account}</td><td>{e.code}</td></tr>)}</tbody></table></details>}
  </Panel>;
}

function ForwardTestsPanel({ status, onImport, importing }) {
  const accounts = status?.accounts || [];
  const last = status?.last_successful_import;
  return <Panel title="Forward tests · Journal import" extra={<button className="cw-mini" type="button" onClick={onImport} disabled={importing}><RefreshCw size={13} /> {importing ? 'Importing…' : 'Import now'}</button>}>
    <div className="cw-table-scroll"><table className="cw-table"><thead><tr>{['Account', 'Mode', 'Trades', 'Net P&L', 'Win %', 'Avg R'].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>
      {accounts.map(a => <tr key={a.tus_account}><td>{a.tus_account}</td><td>{a.playback ? 'Playback' : 'SIM / live'}</td><td>{a.journal_trades}</td>
        <td className={a.net_pnl < 0 ? 'cw-red' : 'cw-green'}>{money(a.net_pnl)}</td>
        <td>{a.journal_trades ? Math.round(100 * (a.wins || 0) / a.journal_trades) + '%' : '—'}</td><td>{a.avg_r ?? '—'}</td></tr>)}
      {!accounts.length && <tr><td colSpan="6" className="cw-table-empty">No TUS trades imported yet.</td></tr>}
    </tbody></table></div>
    <p className="cw-muted" style={{ fontSize: 12 }}>
      {last ? `Last import ${clock(last.finished_at)}: ${last.inserted} new, ${last.updated} updated, ${last.unchanged} unchanged.` : 'Waiting for the first import.'}
      {' '}Playback accounts are excluded from "All Accounts" in the Journal.
      {status?.auto_import?.last_error && <span className="cw-red"> Import error: {status.auto_import.last_error}</span>}
    </p>
  </Panel>;
}

function DiagnosticsPanel({ live, error }) {
  const [copied, setCopied] = useState('');
  const copy = async () => {
    try { const r = await tccApi.diagnostics(); await navigator.clipboard.writeText(JSON.stringify({ diagnostics: r.data, live }, null, 2)); setCopied('Copied'); }
    catch (e) { setCopied('Copy failed: ' + e.message); }
  };
  const d = live?.bridge_discovery || {};
  return <Panel title="System diagnostics" extra={<button className="cw-mini" type="button" onClick={copy}><Copy size={13} /> {copied || 'Copy diagnostics'}</button>}>
    {error && <div className="cw-warning" role="alert">TCC backend: {error}</div>}
    <table className="cw-table"><tbody>
      <tr><th>NinjaTrader folder</th><td>{live?.ninjatrader_dir || 'not found'}</td></tr>
      <tr><th>TUS journal</th><td>{live?.paths?.journal || '—'}</td></tr>
      <tr><th>TEM bridge</th><td>{live?.paths?.bridge || '—'} · {d.tem_files ?? 0} TEM files · {d.tmp_count ?? 0} abandoned .tmp</td></tr>
      <tr><th>Fresh if newer than</th><td>TEM {live?.thresholds_seconds?.tem}s · charts {live?.thresholds_seconds?.charts}s</td></tr>
      <tr><th>Checked</th><td>{clock(live?.checked_at)} · ET {live?.market_session?.et_time?.slice(11) || '—'}</td></tr>
    </tbody></table>
    {d.tmp_count > 1000 && <p className="cw-warning">{d.tmp_count.toLocaleString()} abandoned .tmp files in the bridge folder. Delete them only after closing NinjaTrader (see R10 notes).</p>}
  </Panel>;
}

export default function TccDashboard({ onNavigate }) {
  const [live, setLive] = useState(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try { const r = await tccApi.live(); if (active) { setLive(r.data); setError(''); } }
      catch (e) { if (active) setError(e.message); }
    };
    poll(); const t = setInterval(poll, 3000);
    return () => { active = false; clearInterval(t); };
  }, []);
  const loadStatus = useCallback(async () => {
    try { const r = await tccApi.importStatus(); setStatus(r.data); } catch { /* shown via live error */ }
  }, []);
  useEffect(() => { loadStatus(); const t = setInterval(loadStatus, 15000); return () => clearInterval(t); }, [loadStatus]);
  const runImport = async () => { setImporting(true); try { await tccApi.importRun(); await loadStatus(); } finally { setImporting(false); } };

  const session = live?.market_session;
  const mode = live?.execution_mode;
  const hb = live?.tem_shared_heartbeat;
  return <div className="cw-workspace">
    <div className="cw-heading">
      <div><h1>Trading Overview</h1><p>TUS · Ultimate System &nbsp; | &nbsp; TEE · Entry Engine &nbsp; | &nbsp; TEM · Execution Manager</p></div>
      <div className="cw-header-status">
        <Chip state={session ? (session.open ? 'live' : 'default') : undefined} label={session ? (session.open ? (session.rth ? 'Market open · RTH' : 'Market open · ETH') : 'Market closed') : 'Session —'} title={session?.note} />
        <Chip state={mode?.value === 'SIM' ? 'live' : mode?.value === 'PLAYBACK' ? 'stale' : 'default'} label={`Automation: ${mode?.value || '—'}`} title={mode?.note} />
        <Chip state={hb?.state} label={hb ? `TEM ${STATE_LABEL[hb.state] || hb.state} · ${age(hb.age_seconds)}` : 'TEM —'} title={hb?.note} />
        <small>Read-only · 3s refresh</small>
      </div>
    </div>
    {error && <div className="cw-warning" role="alert">Cannot reach the TCC backend: {error}</div>}
    {!error && live && !live.ninjatrader_dir && <div className="cw-warning" role="alert">NinjaTrader 8 folder not found. Checked: {(live.paths?.candidates_checked || []).join(' | ')}</div>}
    <div className="cw-grid cw-three">{(live?.markets || [{ family: 'ES' }, { family: 'NQ' }, { family: 'YM' }]).map(m =>
      live ? <MarketPanel key={m.family} m={m} session={session} /> : <Panel key={m.family} title={m.family}><Empty label="Loading…" /></Panel>)}</div>
    <div className="cw-grid cw-three">
      <SetupsPanel markets={live?.markets} />
      <ExecutionPanel markets={live?.markets} shared={live?.tem_shared_order_status} />
      <ForwardTestsPanel status={status} onImport={runImport} importing={importing} />
    </div>
    <div className="cw-grid cw-two">
      <Panel title="Risk / Trade plan"><p className="cw-muted">TEM enforces risk in NinjaTrader; TCC does not change TEM settings.</p>
        <button className="cw-mini" type="button" onClick={() => onNavigate && onNavigate('control-risk')}>Open calculator (utility)</button></Panel>
      <DiagnosticsPanel live={live} error={error} />
    </div>
    <TusJournal compact />
  </div>;
}
