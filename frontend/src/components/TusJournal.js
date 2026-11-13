import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { tccApi } from '../api';
import './control-workspace.css';

// R10: TUS trade master as recorded by NinjaTrader, plus where each trade lives in the
// journal database (Trade Log, Calendar, Reports and R use those imported rows).
const money = value => typeof value === 'number' ? value.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : '—';
const when = iso => { if (!iso) return '—'; const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(); };

export default function TusJournal({ compact = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [playback, setPlayback] = useState('sim');
  const [account, setAccount] = useState('all');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { const res = await tccApi.journal(); setData(res.data); setError(''); }
    catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { load(); const timer = setInterval(load, 15000); return () => clearInterval(timer); }, [load]);
  const runImport = async () => { setBusy(true); try { await tccApi.importRun(); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); } };

  const trades = (data?.trades || []).filter(t => (playback === 'all' || (playback === 'playback' ? t.playback : !t.playback)) && (account === 'all' || t.Account === account));
  const pnl = trades.reduce((sum, t) => sum + (t.net_pnl || 0), 0);
  const winners = trades.filter(t => t.net_pnl > 0).length;
  const imported = trades.filter(t => t.journal?.journal_trade_id).length;
  const status = data?.import_status;
  const last = status?.last_successful_import;
  return <section className="cw-panel" style={{ padding: 16, marginTop: 12 }}>
    <header className="cw-panel-head">
      <strong>{compact ? 'TUS Trades · NinjaTrader journal' : 'TUS Trades · NinjaTrader journal → Trading Journal'}</strong>
      <span className="cw-inline" style={{ alignItems: 'center' }}>
        <span className={'cw-status ' + (data?.database_imported ? 'positive' : 'neutral')}>{data?.database_imported ? 'Imported to journal' : 'Not imported yet'}</span>
        <button type="button" className="cw-mini" onClick={runImport} disabled={busy}><RefreshCw size={13} /> {busy ? 'Importing…' : 'Import now'}</button>
      </span>
    </header>
    {error && <div className="cw-warning">{error}</div>}
    {data && !data.available && <div className="cw-warning">{data.error || data.reason || 'Waiting for TUS journal…'}<div style={{ fontSize: 11, marginTop: 6 }}>Checked: {(data.paths_checked || []).map(p => p.path).join(' | ') || '—'}</div></div>}
    <div className="cw-inline" style={{ gap: 8, flexWrap: 'wrap', margin: '12px 0', alignItems: 'center' }}>
      <label>Mode <select value={playback} onChange={e => setPlayback(e.target.value)}><option value="sim">SIM / non-Playback</option><option value="playback">Playback</option><option value="all">All (separate classification)</option></select></label>
      <label>Account <select value={account} onChange={e => setAccount(e.target.value)}><option value="all">All accounts</option>{Object.keys(data?.accounts || {}).map(a => <option key={a} value={a}>{a}</option>)}</select></label>
      <span>Trades: <strong>{trades.length}</strong></span><span>Net: <strong className={pnl < 0 ? 'cw-red' : 'cw-green'}>{money(pnl)}</strong></span>
      <span>Win rate: <strong>{trades.length ? (100 * winners / trades.length).toFixed(1) + '%' : '—'}</strong></span>
      <span>In journal: <strong>{imported}/{trades.length}</strong></span>
    </div>
    <div className="cw-table-scroll"><table className="cw-table"><thead><tr>{['Close', 'Account', 'Instrument', 'Side', 'Setup', 'Qty', 'Net P&L', 'R', 'Fills', 'Journal'].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>
      {trades.slice(0, compact ? 8 : 1000).map(t => <tr key={`${t.Account}:${t.TradeId}`}>
        <td>{when(t.close_utc)}</td><td>{t.Account}{t.playback ? ' · Playback' : ''}</td><td>{t.Instrument}</td><td>{t.Side}</td>
        <td>{t.setup_tag || t.forward?.[0]?.setup || 'Unclassified'}</td><td>{t.Quantity}</td>
        <td className={t.net_pnl < 0 ? 'cw-red' : 'cw-green'}>{money(t.net_pnl)}</td><td>{t.journal?.r_multiple ?? '—'}</td>
        <td title={(t.executions || []).map(x => `${x.Action} ${x.Quantity}@${x.Price}`).join(' | ')}>{t.execution_count}{t.missing_execution_ids?.length ? ' ⚠' : ''}</td>
        <td title={t.journal?.conflict || t.journal?.trade_group || ''}>{t.journal?.deleted_in_journal_at ? 'Deleted in journal' : t.journal?.journal_trade_id ? (t.journal.conflict ? 'Edited (kept)' : 'Imported') : 'Pending'}</td></tr>)}
      {!trades.length && <tr><td colSpan="10" className="cw-table-empty">No completed TUS trades found for this filter.</td></tr>}
    </tbody></table></div>
    <p className="cw-muted" style={{ fontSize: 12, marginTop: 10 }}>
      Source: {data?.source_directory || 'Not found'}. One row per completed trade; a two-leg TP1/TP2 trade is one trade with its fills attached.
      {' '}Imported trades appear in Trade Log, Calendar and Reports under the “TUS · account” journal accounts. Playback accounts are excluded from “All Accounts”.
      {last ? ` Last import: ${when(last.finished_at)}.` : ''}
    </p>
  </section>;
}
