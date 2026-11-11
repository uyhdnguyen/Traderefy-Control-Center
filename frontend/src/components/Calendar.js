import { useState, useEffect } from 'react';
import YearBehind from '../v3/YearBehind';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { calendarApi, kpisApi, yearlyKpisApi } from '../api';
import CalendarGrid from './CalendarGrid';
import { PageHeader, KpiStrip, KpiCell } from './ui';

const fmtPnl = (v) => {
  const n = Number(v || 0);
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 1000) {
    const k = abs / 1000;
    return `${sign}$${k % 1 === 0 ? k.toFixed(0) : k.toFixed(2).replace(/\.?0+$/, '')}K`;
  }
  return `${sign}$${abs % 1 === 0 ? abs.toFixed(0) : abs.toFixed(1)}`;
};
const signedPnl = (v) => (Number(v) > 0 ? '+' : '') + fmtPnl(v);

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function getDaysInMonth(year, month) { return new Date(year, month, 0).getDate(); }
function getFirstDayOfMonth(year, month) {
  const d = new Date(year, month - 1, 1).getDay();
  return (d + 6) % 7;
}
const pad = (n) => String(n).padStart(2, '0');

function ViewToggle({ view, setView }) {
  return (
    <div className="seg" role="group" aria-label="Calendar view">
      <button type="button" className="seg-btn" aria-pressed={view === 'month'} onClick={() => setView('month')}>Month</button>
      <button type="button" className="seg-btn" aria-pressed={view === 'year'} onClick={() => setView('year')}>Year</button>
    </div>
  );
}

// ── Year view: grid of 12 month cards ─────────────────────────────────────────

function MonthCard({ data, monthIdx, year, onClick, isCurrent, isFuture }) {
  const name = MONTHS_SHORT[monthIdx];
  if (isFuture) {
    return (
      <div className="month-card" style={{ opacity: 0.45 }} aria-label={`${MONTHS[monthIdx]} ${year}, upcoming`}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>{name}</div>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 'auto' }}>Upcoming</div>
      </div>
    );
  }

  if (!data || !data.has_data) {
    return (
      <div className="month-card" aria-label={`${MONTHS[monthIdx]} ${year}, no trades`}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>{name}</div>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 'auto' }}>No trades</div>
      </div>
    );
  }

  const pnlTone = data.net_pnl > 0 ? 'pos' : data.net_pnl < 0 ? 'neg' : '';
  const pfTone = data.profit_factor == null || data.profit_factor >= 1.5 ? 'pos' : data.profit_factor >= 1 ? 'text-purple' : 'neg';
  const wrTone = data.win_rate >= 55 ? 'pos' : 'neg';
  const ratio = data.avg_loss !== 0 ? Math.abs(data.avg_win / data.avg_loss).toFixed(2) : '--';

  return (
    <button
      type="button"
      className={`month-card${isCurrent ? ' current' : ''}`}
      onClick={() => onClick(monthIdx + 1)}
      aria-label={`${MONTHS[monthIdx]} ${year}: ${signedPnl(data.net_pnl)}, ${data.total_trades} trades. Open month`}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', width: '100%', gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>{name}</span>
        <span className={`num ${pnlTone}`} style={{ fontSize: 20, fontWeight: 600, fontFamily: 'var(--font-display)' }}>
          {signedPnl(data.net_pnl)}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, width: '100%' }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Win %</div>
          <div className={`num ${wrTone}`} style={{ fontSize: 15, fontWeight: 600 }}>{data.win_rate.toFixed(1)}%</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Prof. F</div>
          <div className={`num ${pfTone}`} style={{ fontSize: 15, fontWeight: 600 }}>{data.profit_factor == null ? '∞' : data.profit_factor.toFixed(2)}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Avg W/L</div>
          <div className="num" style={{ fontSize: 15, fontWeight: 600 }}>{ratio}</div>
        </div>
      </div>

      <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'space-between', width: '100%', fontSize: 12.5, color: 'var(--text-secondary)' }}>
        <span><span className="num">{data.total_trades}</span> trades</span>
        <span><span className="num">{data.trading_days}</span> days</span>
      </div>
    </button>
  );
}

function YearView({ year, setYear, accountId, onMonthClick, view, setView }) {
  const [yearData, setYearData] = useState(null);
  const [loading, setLoading] = useState(true);
  const today = new Date();
  const currentYear = today.getFullYear();
  const currentMonth = today.getMonth() + 1;

  useEffect(() => {
    setLoading(true);
    const params = { year };
    if (accountId != null) params.account_id = accountId;
    yearlyKpisApi.get(params)
      .then(r => { setYearData(r.data); setLoading(false); })
      .catch(() => { setYearData(null); setLoading(false); });
  }, [year, accountId]);

  // Compute year totals from months with data
  const monthsWithData = yearData ? yearData.filter(m => m.has_data) : [];
  const yearPnl = monthsWithData.reduce((s, m) => s + m.net_pnl, 0);
  const totalTrades = monthsWithData.reduce((s, m) => s + m.total_trades, 0);
  const totalWinners = monthsWithData.reduce((s, m) => s + m.winning_trades, 0);
  const yearWinRate = totalTrades > 0 ? (totalWinners / totalTrades * 100).toFixed(1) : '--';

  return (
    <div>
      <PageHeader
        title={<span className="num">{year}</span>}
        subtitle="Year view. Select a month to open it."
        actions={<>
          <button type="button" className="cal-nav" onClick={() => setYear(y => y - 1)} aria-label="Previous year"><ChevronLeft size={18} /></button>
          <button type="button" className="cal-nav" onClick={() => setYear(y => y + 1)} aria-label="Next year"><ChevronRight size={18} /></button>
          <button type="button" className="btn btn-secondary" onClick={() => setYear(currentYear)}>This year</button>
          <ViewToggle view={view} setView={setView} />
        </>}
      />

      {monthsWithData.length > 0 && (
        <KpiStrip label="Year summary">
          <KpiCell label="YTD P&L" value={<span className="num">{signedPnl(yearPnl)}</span>} tone={yearPnl > 0 ? 'pos' : yearPnl < 0 ? 'neg' : undefined} />
          <KpiCell label="Win %" value={<span className="num">{yearWinRate !== '--' ? `${yearWinRate}%` : '--'}</span>} tone={Number(yearWinRate) >= 55 ? 'pos' : undefined} />
          <KpiCell label="Trades" value={<span className="num">{totalTrades.toLocaleString('en-US')}</span>} />
        </KpiStrip>
      )}

      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 12 }}>
          {[...Array(12)].map((_, i) => <div key={i} className="skeleton" style={{ height: 136, borderRadius: 8 }} />)}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 12 }}>
          {(yearData || []).map((mData, i) => {
            const isFuture = year > currentYear || (year === currentYear && i + 1 > currentMonth);
            const isCurrent = year === currentYear && i + 1 === currentMonth;
            return (
              <MonthCard
                key={i}
                data={mData}
                monthIdx={i}
                year={year}
                onClick={onMonthClick}
                isCurrent={isCurrent}
                isFuture={isFuture}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Month view ─────────────────────────────────────────────────────────────────

function MonthView({ year, month, setYear, setMonth, accountId, onDayClick, view, setView }) {
  const today = new Date();
  const [dayData, setDayData] = useState({});
  const [loading, setLoading] = useState(true);
  const [monthKpis, setMonthKpis] = useState(null);

  useEffect(() => {
    setLoading(true);
    const lastDay = new Date(year, month, 0).getDate();
    const dateFrom = `${year}-${pad(month)}-01`;
    const dateTo = `${year}-${pad(month)}-${pad(lastDay)}`;
    const params = { year, month };
    const kpiParams = { date_from: dateFrom, date_to: dateTo };
    if (accountId != null) { params.account_id = accountId; kpiParams.account_id = accountId; }

    calendarApi.get(params)
      .then(r => {
        const map = {};
        for (const d of r.data) map[d.date] = d;
        setDayData(map);
        setLoading(false);
      })
      .catch(() => setLoading(false));

    kpisApi.get(kpiParams)
      .then(r => setMonthKpis(r.data))
      .catch(() => setMonthKpis(null));
  }, [year, month, accountId]);

  const prevMonth = () => { if (month === 1) { setYear(y => y - 1); setMonth(12); } else setMonth(m => m - 1); };
  const nextMonth = () => { if (month === 12) { setYear(y => y + 1); setMonth(1); } else setMonth(m => m + 1); };
  const goToday = () => { setYear(today.getFullYear()); setMonth(today.getMonth() + 1); };

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfMonth(year, month);
  const cells = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  const allWeeks = [];
  for (let i = 0; i < cells.length; i += 7) allWeeks.push(cells.slice(i, i + 7));
  const weeks = allWeeks.filter(w => w.slice(0, 5).some(d => d !== null));

  const allDays = Object.values(dayData);
  const monthPnl = allDays.reduce((s, d) => s + d.net_pnl, 0);
  const tradingDays = allDays.length;

  const pf = monthKpis ? monthKpis.profit_factor : undefined;
  const pfTone = monthKpis && (pf == null || pf >= 1.5) ? 'pos' : undefined;

  return (
    <div>
      <PageHeader
        title={<>{MONTHS[month - 1]} <span className="num">{year}</span></>}
        subtitle="Select a trading day to open its Day Review."
        actions={<>
          <button type="button" className="cal-nav" onClick={prevMonth} aria-label="Previous month"><ChevronLeft size={18} /></button>
          <button type="button" className="cal-nav" onClick={nextMonth} aria-label="Next month"><ChevronRight size={18} /></button>
          <button type="button" className="btn btn-secondary" onClick={goToday}>This month</button>
          <ViewToggle view={view} setView={setView} />
        </>}
      />

      <KpiStrip label="Month summary">
        <KpiCell label="MTD P&L" value={<span className="num">{signedPnl(monthPnl)}</span>} tone={monthPnl > 0 ? 'pos' : monthPnl < 0 ? 'neg' : undefined} />
        <KpiCell
          label="Win %"
          value={<span className="num">{monthKpis ? `${Number(monthKpis.win_rate || 0).toFixed(1)}%` : '--'}</span>}
          tone={monthKpis && monthKpis.win_rate >= 55 ? 'pos' : undefined}
        />
        <KpiCell
          label="Prof. Factor"
          value={<span className={`num ${monthKpis && pf != null && pf >= 1 && pf < 1.5 ? 'text-purple' : ''}`}>{monthKpis ? (pf == null ? '∞' : Number(pf).toFixed(2)) : '--'}</span>}
          tone={pfTone}
        />
        <KpiCell
          label="Avg W/L"
          value={<span className="num">{monthKpis && Math.abs(monthKpis.avg_loss || 0) > 0
            ? (Math.abs(monthKpis.avg_win || 0) / Math.abs(monthKpis.avg_loss)).toFixed(2)
            : '--'}</span>}
        />
        <KpiCell label="Trading days" value={<span className="num">{tradingDays}</span>} />
      </KpiStrip>

      <section className="card">
        {loading ? (
          <div className="empty" role="status">Loading...</div>
        ) : (
          <CalendarGrid weeks={weeks} dayData={dayData} year={year} month={month} onDayClick={onDayClick} size="full" />
        )}
      </section>
    </div>
  );
}

// ── Main Calendar (view switcher) ──────────────────────────────────────────────

export default function Calendar({ accountId, onDayClick }) {
  const today = new Date();
  const [view, setView] = useState('month');
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);

  const switchToMonth = (m) => { setMonth(m); setView('month'); };

  return (
    <>
      {view === 'year' ? (
        <YearView year={year} setYear={setYear} accountId={accountId} onMonthClick={switchToMonth} view={view} setView={setView} />
      ) : (
        <MonthView year={year} month={month} setYear={setYear} setMonth={setMonth} accountId={accountId} onDayClick={onDayClick} view={view} setView={setView} />
      )}

      {/* the month grid cannot tell you where the account stood; this can */}
      <section className="v3-band" style={{ borderBottom: 0 }}>
        <div className="v3-sec-head">
          <div>
            <h2 className="v3-h">The year behind it</h2>
            <p className="v3-h-sub">Each month closing where the next one opens</p>
          </div>
        </div>
        <YearBehind accountId={accountId} />
      </section>
    </>
  );
}
