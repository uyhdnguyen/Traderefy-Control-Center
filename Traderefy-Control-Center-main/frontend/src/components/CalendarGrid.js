// Shared trading-calendar grid (Mon-Fri) with filled day cells + week-summary
// cards the same width as a day column. Used by the Dashboard mini calendar
// and the full Calendar page. Pass size="mini" | "full".
//
// Day states are kept visually distinct: a traded day is tinted by result
// (win / loss), an exactly-flat day is neutral, a past day without trades is
// plain, and future days are dimmed. Clicking a traded day calls onDayClick,
// which opens Day Review, exactly as before.

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const fmtK = (v) => {
  const n = Number(v || 0);
  const s = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (a >= 1000) {
    const k = a / 1000;
    return `${s}$${k % 1 === 0 ? k.toFixed(0) : k.toFixed(1)}K`;
  }
  return `${s}$${Math.round(a)}`;
};
const signedK = (v) => (Number(v) > 0 ? '+' : '') + fmtK(v);

const SIZES = {
  mini: { rowH: 92, headH: 32, gap: 8, cardGap: 12, pnl: 18, num: 12, meta: 11.5, wkPnl: 16 },
  full: { rowH: 138, headH: 38, gap: 8, cardGap: 14, pnl: 25, num: 13, meta: 12.5, wkPnl: 20 },
};

export default function CalendarGrid({ weeks, dayData, year, month, onDayClick, size = 'full' }) {
  const S = SIZES[size] || SIZES.full;
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  const dateKey = (d) => d
    ? `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    : null;
  const isToday = (d) => d && year === today.getFullYear()
    && month === today.getMonth() + 1 && d === today.getDate();

  const weekStats = (week) => {
    let pnl = 0, days = 0;
    for (const d of week.slice(0, 5)) {
      const k = dateKey(d);
      if (k && dayData[k]) { pnl += dayData[k].net_pnl; days++; }
    }
    return { pnl, days };
  };

  return (
    // Below ~600px the grid keeps a readable minimum width and scrolls sideways
    // (same overflow cue as the tables) instead of truncating P&L to "+".
    <div className="scroll-x cal-scroll">
    <div className={`cal-inner${size === 'mini' ? '' : ' cal-inner-full'}`} style={{ display: 'flex', gap: S.cardGap, alignItems: 'flex-start' }}>

      {/* ── Day grid (Mon-Fri) ── */}
      <div style={{ flex: 5, minWidth: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 6 }}>
          {WEEKDAYS.map(d => (
            <div key={d} style={{
              height: S.headH, display: 'flex', alignItems: 'center',
              fontSize: 13, color: 'var(--text-secondary)', paddingLeft: 4,
            }}>{d}</div>
          ))}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {weeks.map((week, wi) => (
            <div key={wi} style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 6 }}>
              {week.slice(0, 5).map((d, di) => {
                const key = dateKey(d);
                const data = key ? dayData[key] : null;
                const tod = isToday(d);
                const future = key && key > todayKey;
                const pnl = data ? Number(data.net_pnl) : 0;
                const tone = !data ? null : pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : 'flat';
                const bg = !d
                  ? 'transparent'
                  : tone === 'pos' ? 'var(--cal-pos)'
                    : tone === 'neg' ? 'var(--cal-neg)'
                      : tone === 'flat' ? 'var(--surface-control)'
                        : 'var(--surface-inset)';
                const bar = tone === 'pos' ? 'var(--result-pos)' : tone === 'neg' ? 'var(--result-neg)' : null;
                const open = () => data && onDayClick && onDayClick(key);
                const label = data
                  ? `${MONTHS_SHORT[month - 1]} ${d}: ${signedK(pnl)}, ${data.trade_count} trade${data.trade_count !== 1 ? 's' : ''}, ${data.win_rate}% win${data.has_diary ? ', diary entry' : ''}. Open Day Review`
                  : undefined;

                return (
                  <div
                    key={di}
                    className={`cal-day${data ? ' has-data' : ''}`}
                    onClick={open}
                    role={data ? 'button' : undefined}
                    tabIndex={data ? 0 : undefined}
                    aria-label={label}
                    onKeyDown={data ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } } : undefined}
                    style={{
                      height: S.rowH,
                      background: bg,
                      borderRadius: 'var(--radius-md)',
                      position: 'relative',
                      boxShadow: bar ? `inset 3px 0 0 ${bar}` : undefined,
                      opacity: future ? 0.55 : 1,
                      padding: size === 'mini' ? '8px 10px' : '10px 14px',
                      display: 'flex',
                      flexDirection: 'column',
                      overflow: 'hidden',
                    }}
                  >
                    {d && (
                      <>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          {tod ? (
                            <span className="num" style={{
                              display: 'grid', placeItems: 'center', minWidth: 22, height: 22, padding: '0 5px',
                              borderRadius: 11, background: 'var(--accent-line)',
                              color: 'var(--surface-page)', fontSize: S.num, fontWeight: 700,
                            }} aria-label={`Today, ${d}`}>{d}</span>
                          ) : (
                            <span className="num" style={{ fontSize: S.num, color: data ? 'var(--text-secondary)' : 'var(--text-tertiary)' }}>{d}</span>
                          )}
                          {data?.has_diary && (
                            <span title="Diary entry" style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent-line)' }} />
                          )}
                        </div>

                        {data && (
                          <div style={{ marginTop: 'auto', minWidth: 0 }}>
                            <div className={`num ${tone === 'flat' ? '' : tone}`} style={{
                              fontSize: S.pnl, fontWeight: 600, lineHeight: 1.1, letterSpacing: '-0.01em',
                              fontFamily: 'var(--font-display)',
                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                            }}>{signedK(pnl)}</div>
                            <div style={{ fontSize: S.meta, color: 'var(--text-secondary)', marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              <span className="num">{data.trade_count}</span> trade{data.trade_count !== 1 ? 's' : ''}
                              {size === 'mini' ? ' · ' : <br />}
                              <span className="num">{data.win_rate}%</span> win
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* ── Week-summary cards (same width as one day column) ── */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ height: S.headH, display: 'flex', alignItems: 'center', fontSize: 13, color: 'var(--text-secondary)', paddingLeft: 4 }}>Week</div>
        {weeks.map((week, wi) => {
          const { pnl, days } = weekStats(week);
          return (
            <div key={wi} style={{
              height: S.rowH,
              borderRadius: 'var(--radius-md)',
              display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 4,
              padding: `0 ${size === 'mini' ? 10 : 14}px`,
              background: 'var(--surface-inset)',
              minWidth: 0,
            }}>
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Week {wi + 1}</div>
              {days === 0 ? (
                <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>No sessions</div>
              ) : (
                <>
                  <div className={`num ${toneClass(pnl)}`} style={{ fontSize: S.wkPnl, fontWeight: 600, fontFamily: 'var(--font-display)', whiteSpace: 'nowrap' }}>
                    {signedK(pnl)}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    <span className="num">{days}</span> day{days !== 1 ? 's' : ''}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
    </div>
  );
}

function toneClass(n) { return n > 0 ? 'pos' : n < 0 ? 'neg' : ''; }
