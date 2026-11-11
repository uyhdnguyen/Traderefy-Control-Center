import { useState, useRef, useEffect } from 'react';
import { ChevronLeft, ChevronRight, ChevronDown, Calendar, X } from 'lucide-react';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

function toStr(d) {
  if (!d) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}


function fmtLabel(s) {
  if (!s) return '—';
  const [y, m, d] = s.split('-');
  return `${MONTHS[Number(m) - 1].slice(0, 3)} ${d}, ${y}`;
}

function getPresets() {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const dow = t.getDay();
  const monday = new Date(t); monday.setDate(t.getDate() - ((dow + 6) % 7));
  const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
  const mStart = new Date(t.getFullYear(), t.getMonth(), 1);
  const mEnd = new Date(t.getFullYear(), t.getMonth() + 1, 0);
  const l30 = new Date(t); l30.setDate(t.getDate() - 29);
  const lmStart = new Date(t.getFullYear(), t.getMonth() - 1, 1);
  const lmEnd = new Date(t.getFullYear(), t.getMonth(), 0);
  const qm = Math.floor(t.getMonth() / 3) * 3;
  const qStart = new Date(t.getFullYear(), qm, 1);
  const qEnd = new Date(t.getFullYear(), qm + 3, 0);
  const ytd = new Date(t.getFullYear(), 0, 1);
  return [
    { label: 'Today',              from: t,      to: t      },
    { label: 'This week',          from: monday, to: sunday },
    { label: 'This month',         from: mStart, to: mEnd   },
    { label: 'Last 30 days',       from: l30,    to: t      },
    { label: 'Last month',         from: lmStart,to: lmEnd  },
    { label: 'This quarter',       from: qStart, to: qEnd   },
    { label: 'YTD (year to date)', from: ytd,    to: t      },
  ];
}

function CalendarMonth({ year, month, fromStr, toStr: toS, hoverStr, selecting, onDayClick, onDayHover }) {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDow = new Date(year, month, 1).getDay();
  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  const todayStr = toStr(new Date());

  function dayStr(d) {
    return `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
  }

  function rangeEnd() {
    if (selecting && hoverStr) return hoverStr > selecting ? hoverStr : selecting;
    return toS;
  }
  function rangeStart() {
    if (selecting && hoverStr) return hoverStr < selecting ? hoverStr : selecting;
    return fromStr;
  }

  const rStart = rangeStart();
  const rEnd = rangeEnd();

  return (
    <div style={{ minWidth: 220 }}>
      <div style={{ fontWeight: 600, fontSize: 14, textAlign: 'center', marginBottom: 8, color: 'var(--text-primary)' }}>
        {MONTHS[month]} {year}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '2px 0' }}>
        {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(d => (
          <div key={d} style={{ textAlign: 'center', fontSize: 11.5, color: 'var(--text-secondary)', padding: '4px 0' }}>{d}</div>
        ))}
        {weeks.map((week, wi) => week.map((d, di) => {
          if (!d) return <div key={`e${wi}-${di}`} />;
          const ds = dayStr(d);
          const isStart = ds === fromStr || ds === selecting;
          const isEnd = ds === toS || (selecting && hoverStr && ds === rangeEnd());
          const inRange = rStart && rEnd && ds > rStart && ds < rEnd;
          const isToday = ds === todayStr;
          const isSelected = ds === fromStr || ds === toS;

          const cls = ['rng-day', isStart || isEnd ? 'edge' : '', inRange ? 'in-range' : '', isToday ? 'today' : ''].filter(Boolean).join(' ');
          return (
            <button
              type="button"
              key={ds}
              className={cls}
              onClick={() => onDayClick(ds)}
              onMouseEnter={() => onDayHover(ds)}
              onFocus={() => onDayHover(ds)}
              aria-label={fmtLabel(ds)}
              aria-pressed={isSelected}
            >
              {d}
            </button>
          );
        }))}
      </div>
    </div>
  );
}

export default function DateRangePicker({ dateFrom, dateTo, onChange }) {
  const [open, setOpen] = useState(false);
  const [selecting, setSelecting] = useState(null);
  const [hover, setHover] = useState(null);
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth() === 0 ? 11 : today.getMonth() - 1);
  const [viewYearR, setViewYearR] = useState(today.getMonth() === 0 ? today.getFullYear() - 1 : today.getFullYear());
  const ref = useRef();

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const t = new Date();
    const lm = t.getMonth() === 0 ? 11 : t.getMonth() - 1;
    const ly = t.getMonth() === 0 ? t.getFullYear() - 1 : t.getFullYear();
    setViewYear(ly);
    setViewMonth(lm);
    setViewYearR(lm === 11 ? ly + 1 : ly);
  }, []);

  const rightMonth = viewMonth === 11 ? 0 : viewMonth + 1;
  const rightYear = viewMonth === 11 ? viewYearR : viewYearR;

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
        setSelecting(null);
        setHover(null);
      }
    }
    function handleKey(e) {
      if (e.key === 'Escape') { setOpen(false); setSelecting(null); setHover(null); }
    }
    if (open) {
      document.addEventListener('mousedown', handleClick);
      document.addEventListener('keydown', handleKey);
    }
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  function prevMonth() {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); setViewYearR(y => y - 1); }
    else { setViewMonth(m => m - 1); }
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); setViewYearR(y => y + 1); }
    else { setViewMonth(m => m + 1); }
  }

  function handleDayClick(ds) {
    if (!selecting) {
      setSelecting(ds);
      setHover(null);
    } else {
      const from = ds < selecting ? ds : selecting;
      const to = ds < selecting ? selecting : ds;
      onChange({ dateFrom: from, dateTo: to });
      setSelecting(null);
      setHover(null);
      setOpen(false);
    }
  }

  function applyPreset(preset) {
    onChange({ dateFrom: toStr(preset.from), dateTo: toStr(preset.to) });
    setSelecting(null);
    setHover(null);
    setOpen(false);
  }

  function clearRange() {
    onChange({ dateFrom: '', dateTo: '' });
    setSelecting(null);
    setHover(null);
  }

  const hasRange = dateFrom || dateTo;
  const displayText = selecting
    ? `${fmtLabel(selecting)} → ...`
    : hasRange
    ? `${fmtLabel(dateFrom)}  →  ${fmtLabel(dateTo)}`
    : 'All time';

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {/* Trigger button + separate clear control (no nested interactive elements) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        <button
          type="button"
          className="btn btn-secondary"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => { setOpen(v => !v); setSelecting(null); }}
          style={{ color: hasRange ? 'var(--text-primary)' : 'var(--text-secondary)', borderColor: open ? 'var(--accent-line)' : undefined }}
        >
          <Calendar size={15} aria-hidden="true" />
          {displayText}
          <ChevronDown size={14} aria-hidden="true" />
        </button>
        {hasRange && (
          <button type="button" className="btn btn-ghost btn-icon" onClick={clearRange} aria-label="Clear date range" title="Clear date range">
            <X size={14} />
          </button>
        )}
      </div>

      {/* Dropdown panel */}
      {open && (
        <div role="dialog" aria-label="Choose a date range" style={{
          position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 500,
          background: 'var(--surface-panel)', border: '1px solid var(--divider)',
          borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-dropdown)',
          display: 'flex', flexWrap: 'wrap', gap: 0, overflow: 'hidden',
          width: 'max-content', maxWidth: 'calc(100vw - 32px)',
        }}>
          {/* Calendars */}
          <div style={{ padding: '16px 20px', flex: 1 }}>
            {/* Selected range display */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, fontSize: 13 }}>
              <div style={{
                flex: 1, padding: '7px 12px', borderRadius: 'var(--radius-md)',
                background: 'var(--surface-inset)', border: '1px solid var(--divider)',
                color: dateFrom ? 'var(--text-primary)' : 'var(--text-secondary)',
                borderColor: selecting ? 'var(--accent-line)' : 'var(--divider)',
              }}>
                {selecting ? fmtLabel(selecting) : (dateFrom ? fmtLabel(dateFrom) : 'Start date')}
              </div>
              <span style={{ color: 'var(--text-muted)' }}>→</span>
              <div style={{
                flex: 1, padding: '7px 12px', borderRadius: 'var(--radius-md)',
                background: 'var(--surface-inset)', border: '1px solid var(--divider)',
                color: dateTo && !selecting ? 'var(--text-primary)' : 'var(--text-secondary)',
              }}>
                {selecting && hover ? fmtLabel(hover) : (dateTo && !selecting ? fmtLabel(dateTo) : 'End date')}
              </div>
            </div>

            {/* Month nav */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <button type="button" className="cal-nav" onClick={prevMonth} aria-label="Previous month">
                <ChevronLeft size={16} />
              </button>
              <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', justifyContent: 'center' }}>
                <CalendarMonth
                  year={viewYear} month={viewMonth}
                  fromStr={dateFrom} toStr={dateTo}
                  hoverStr={hover} selecting={selecting}
                  onDayClick={handleDayClick} onDayHover={setHover}
                />
                <CalendarMonth
                  year={rightYear} month={rightMonth}
                  fromStr={dateFrom} toStr={dateTo}
                  hoverStr={hover} selecting={selecting}
                  onDayClick={handleDayClick} onDayHover={setHover}
                />
              </div>
              <button type="button" className="cal-nav" onClick={nextMonth} aria-label="Next month">
                <ChevronRight size={16} />
              </button>
            </div>
          </div>

          {/* Presets */}
          <div style={{
            borderLeft: '1px solid var(--divider)',
            padding: '16px 0',
            minWidth: 170,
            flex: '1 0 170px',
            display: 'flex', flexDirection: 'column',
          }}>
            <div className="eyebrow" style={{ padding: '0 20px 8px' }}>Presets</div>
            {getPresets().map(p => {
              const active = dateFrom === toStr(p.from) && dateTo === toStr(p.to);
              return (
                <button
                  type="button"
                  key={p.label}
                  onClick={() => applyPreset(p)}
                  className={`preset-btn${active ? ' active' : ''}`}
                  aria-pressed={active}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
