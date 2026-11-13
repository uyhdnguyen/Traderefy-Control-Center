import { useEffect, useState } from 'react';
import './control-workspace.css';

const money = value => typeof value === 'number' ? value.toLocaleString('en-US', {style:'currency',currency:'USD'}) : '—';
export default function TusJournal({compact=false}) {
  const [data,setData] = useState(null);
  const [error,setError] = useState('');
  const [playback,setPlayback] = useState('sim');
  const [account,setAccount] = useState('all');
  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const res = await fetch('/api/tus/journal/snapshot');
        if (!res.ok) throw Error(`Journal endpoint returned ${res.status}`);
        const json = await res.json();
        if (active) {setData(json);setError('');}
      } catch (e) {if(active)setError(e.message);}
    }
    poll(); const timer=setInterval(poll,10000);
    return ()=>{active=false;clearInterval(timer);};
  }, []);
  const trades=(data?.trades||[]).filter(t => (playback==='all'||(playback==='playback'?t.playback:!t.playback)) && (account==='all'||t.Account===account));
  const pnl=trades.reduce((sum,t)=>sum+(t.net_pnl||0),0);
  const winners=trades.filter(t=>t.net_pnl>0).length;
  return <section className="cw-panel" style={{padding:16,marginTop:12}}>
    <header className="cw-panel-head"><strong>{compact?'TUS Trades · Live Source':'TUS Trade Master · Read-only Journal'}</strong><span className="cw-muted">10s refresh</span></header>
    {error && <div className="cw-warning">{error}</div>}
    {!data?.available && <div className="cw-warning">{data?.error||data?.reason||'Waiting for TUS journal…'}<div style={{fontSize:11,marginTop:6}}>Checked: {(data?.paths_checked||[]).map(p=>p.path).join(' | ')||'—'}</div></div>}
    <div className="cw-inline" style={{gap:8,flexWrap:'wrap',margin:'12px 0'}}>
      <label>Mode <select value={playback} onChange={e=>setPlayback(e.target.value)}><option value="sim">SIM / non-Playback</option><option value="playback">Playback</option><option value="all">All (separate classification)</option></select></label>
      <label>Account <select value={account} onChange={e=>setAccount(e.target.value)}><option value="all">All accounts</option>{Object.keys(data?.accounts||{}).map(a=><option key={a} value={a}>{a}</option>)}</select></label>
      <span>Trades: <strong>{trades.length}</strong></span><span>Net: <strong style={{color:pnl<0?'#f47d7d':'#58d297'}}>{money(pnl)}</strong></span><span>Win rate: <strong>{trades.length?(100*winners/trades.length).toFixed(1)+'%':'—'}</strong></span>
    </div>
    <div className="cw-table-scroll"><table className="cw-table"><thead><tr>{['Close','Account','Instrument','Side','Setup','Qty','Net P&L','Fills','Group'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{trades.slice(0,compact?8:500).map(t=><tr key={`${t.Account}:${t.TradeId}`}><td>{t.CloseTime||'—'}</td><td>{t.Account}</td><td>{t.Instrument}</td><td>{t.Side}</td><td>{t.setup}</td><td>{t.Quantity}</td><td>{money(t.net_pnl)}</td><td title={(t.executions||[]).map(x=>`${x.Action} ${x.Quantity}@${x.Price}`).join(' | ')}>{t.execution_count}{t.missing_execution_ids?.length?' ⚠':''}</td><td>{t.manual_group_id||'—'}</td></tr>)}{!trades.length&&<tr><td colSpan="9">No completed TUS trades found for this filter.</td></tr>}</tbody></table></div>
    <p className="cw-muted" style={{fontSize:12,marginTop:10}}>Source: {data?.source_directory||'Not found'}. Completed trades are counted once; their fills are attached. Playback is separated. This read-only view is NOT yet imported into the Trading-Journal-AI analytics database.</p>
  </section>;
}
