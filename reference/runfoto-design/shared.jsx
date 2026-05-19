/* RunFoto — shared bits */

// Wordmark with orange square dot accent above the dot of the i
const Wordmark = ({ size = 22, color = '#FAFAFA', dot = '#FC5200' }) => {
  // We render "Run" + "F" + "oto", placing a small orange square over the
  // letter "i"... but the wordmark is RunFoto. Spec says: "small orange square
  // dot placed at baseline after or above the 'i'". RunFoto has no 'i'.
  // The spec literally says "above the i" but the name is RunFoto. We'll
  // interpret as: place the orange square dot at the baseline after the o,
  // matching brand mark conventions (Strava-like). The o is the closest
  // circular letter; we'll put the square dot just after the final 'o'.
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'baseline',
      gap: 0,
      fontFamily: "'Space Grotesk', sans-serif",
      fontWeight: 800,
      fontSize: size,
      letterSpacing: '-0.02em',
      color,
      lineHeight: 1,
    }}>
      <span>RunFoto</span>
      <span style={{
        display: 'inline-block',
        width: size * 0.18,
        height: size * 0.18,
        background: dot,
        marginLeft: size * 0.08,
        transform: `translateY(${size * 0.02}px)`,
      }} />
    </span>
  );
};

// Striped placeholder for race photos (we don't have real photos)
const PhotoPH = ({ w = '100%', h = '100%', label, seed = 1, aspect, style = {} }) => {
  // Vary the dark gradient so the grid doesn't look uniform
  const hues = [
    ['#2a2a2e', '#1a1a1d'],
    ['#1f2629', '#13181b'],
    ['#2b2520', '#181412'],
    ['#1d2226', '#101418'],
    ['#26201d', '#15110f'],
    ['#1a1f23', '#0e1215'],
    ['#252025', '#161116'],
    ['#1f231e', '#121610'],
  ];
  const [a, b] = hues[seed % hues.length];
  return (
    <div style={{
      width: w,
      height: h,
      aspectRatio: aspect,
      background: `linear-gradient(135deg, ${a} 0%, ${b} 100%)`,
      backgroundImage: `repeating-linear-gradient(135deg, rgba(255,255,255,0.018) 0 8px, transparent 8px 24px), linear-gradient(135deg, ${a} 0%, ${b} 100%)`,
      position: 'relative',
      overflow: 'hidden',
      ...style,
    }}>
      {label && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9, color: 'rgba(255,255,255,0.18)',
          letterSpacing: '0.08em',
          textAlign: 'center', padding: 8,
        }}>{label}</div>
      )}
    </div>
  );
};

// Action runner illustration placeholder — silhouettes hinted via gradient
const RunnerPH = ({ seed = 1, label, ...rest }) => (
  <PhotoPH seed={seed} label={label} {...rest} />
);

// Bib badge
const Bib = ({ n, size = 'sm', tone = 'cyan' }) => {
  const tones = {
    cyan: { bg: 'rgba(0,212,255,0.12)', fg: '#00D4FF', bd: 'rgba(0,212,255,0.25)' },
    green: { bg: 'rgba(16,185,129,0.14)', fg: '#10B981', bd: 'rgba(16,185,129,0.3)' },
    amber: { bg: 'rgba(245,158,11,0.14)', fg: '#F59E0B', bd: 'rgba(245,158,11,0.3)' },
  };
  const t = tones[tone] || tones.cyan;
  const s = size === 'lg'
    ? { fs: 13, px: 10, py: 5 }
    : size === 'md'
      ? { fs: 11, px: 8, py: 4 }
      : { fs: 10, px: 6, py: 3 };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      fontFamily: "'JetBrains Mono', monospace",
      fontWeight: 600,
      fontSize: s.fs,
      padding: `${s.py}px ${s.px}px`,
      background: t.bg,
      color: t.fg,
      border: `1px solid ${t.bd}`,
      borderRadius: 6,
      letterSpacing: '0.02em',
      lineHeight: 1,
    }}>{n}</span>
  );
};

const Pill = ({ children, tone = 'cyan', dot = false, size = 'sm', style = {} }) => {
  const tones = {
    cyan: { bg: 'rgba(0,212,255,0.10)', fg: '#00D4FF', bd: 'rgba(0,212,255,0.22)' },
    orange: { bg: 'rgba(252,82,0,0.12)', fg: '#FC5200', bd: 'rgba(252,82,0,0.3)' },
    green: { bg: 'rgba(16,185,129,0.12)', fg: '#10B981', bd: 'rgba(16,185,129,0.28)' },
    amber: { bg: 'rgba(245,158,11,0.12)', fg: '#F59E0B', bd: 'rgba(245,158,11,0.28)' },
    red: { bg: 'rgba(239,68,68,0.10)', fg: '#EF4444', bd: 'rgba(239,68,68,0.28)' },
    neutral: { bg: 'rgba(255,255,255,0.04)', fg: '#A1A1A6', bd: '#2A2A2E' },
  };
  const t = tones[tone] || tones.neutral;
  const fs = size === 'md' ? 12 : 10;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontFamily: "'Inter', sans-serif",
      fontWeight: 500,
      fontSize: fs,
      padding: size === 'md' ? '5px 10px' : '4px 8px',
      background: t.bg,
      color: t.fg,
      border: `1px solid ${t.bd}`,
      borderRadius: 999,
      letterSpacing: '0.04em',
      textTransform: 'uppercase',
      ...style,
    }}>
      {dot && (
        <span style={{
          width: 6, height: 6, borderRadius: 99, background: t.fg,
          boxShadow: dot === 'pulse' ? `0 0 0 0 ${t.fg}` : 'none',
          animation: dot === 'pulse' ? 'rfpulse 1.6s ease-out infinite' : 'none',
        }} />
      )}
      {children}
    </span>
  );
};

// Inject keyframes once
if (typeof document !== 'undefined' && !document.getElementById('rfkf')) {
  const s = document.createElement('style');
  s.id = 'rfkf';
  s.textContent = `
    @keyframes rfpulse { 0% { box-shadow: 0 0 0 0 currentColor; } 70% { box-shadow: 0 0 0 6px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
    .rf-cta { font-family: 'Space Grotesk', sans-serif; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
    .rf-num { font-family: 'JetBrains Mono', monospace; font-weight: 500; }
    .rf input::placeholder { color: #6B6B70; }
  `;
  document.head.appendChild(s);
}

// Primary orange CTA button
const CTA = ({ children, size = 'md', icon, full, style = {}, onClick }) => {
  const s = size === 'lg' ? { fs: 13, px: 22, py: 14 } : size === 'sm' ? { fs: 11, px: 14, py: 9 } : { fs: 12, px: 18, py: 12 };
  return (
    <button onClick={onClick} className="rf-cta" style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
      fontSize: s.fs,
      padding: `${s.py}px ${s.px}px`,
      background: '#FC5200',
      color: '#fff',
      border: 'none',
      borderRadius: 8,
      cursor: 'pointer',
      width: full ? '100%' : 'auto',
      ...style,
    }}>
      {icon}
      <span>{children}</span>
    </button>
  );
};

const Ghost = ({ children, size = 'md', full, style = {}, onClick, tone = 'neutral' }) => {
  const s = size === 'lg' ? { fs: 13, px: 22, py: 14 } : size === 'sm' ? { fs: 11, px: 14, py: 9 } : { fs: 12, px: 18, py: 12 };
  const tones = {
    neutral: { fg: '#FAFAFA', bd: '#2A2A2E' },
    red: { fg: '#EF4444', bd: 'rgba(239,68,68,0.4)' },
    danger: { fg: '#EF4444', bd: 'rgba(239,68,68,0.4)' },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <button onClick={onClick} className="rf-cta" style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
      fontSize: s.fs,
      padding: `${s.py}px ${s.px}px`,
      background: 'transparent',
      color: t.fg,
      border: `1px solid ${t.bd}`,
      borderRadius: 8,
      cursor: 'pointer',
      width: full ? '100%' : 'auto',
      ...style,
    }}>{children}</button>
  );
};

// Tiny icon set (line, currentColor)
const I = {
  search: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>,
  bib: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="6" width="16" height="14" rx="2"/><path d="M8 3v4M16 3v4M8 12h8M8 16h5"/></svg>,
  face: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9 10h.01M15 10h.01M9 15c1 1 2 1.5 3 1.5s2-.5 3-1.5"/></svg>,
  download: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg>,
  hires: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M21 17l-4-4-6 6"/></svg>,
  close: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 6l12 12M18 6L6 18"/></svg>,
  share: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/></svg>,
  more: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="currentColor"><circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/></svg>,
  left: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7"/></svg>,
  right: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5l7 7-7 7"/></svg>,
  check: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5L20 7"/></svg>,
  upload: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M7 18a5 5 0 01-1-9.9 7 7 0 0113.4 2.1A4.5 4.5 0 0117 18"/><path d="M12 12v8M9 15l3-3 3 3"/></svg>,
  calendar: (p) => <svg width={p?.s||14} height={p?.s||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>,
  clock: (p) => <svg width={p?.s||14} height={p?.s||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>,
  camera: (p) => <svg width={p?.s||14} height={p?.s||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8h3l2-3h8l2 3h3v12H3z"/><circle cx="12" cy="13" r="4"/></svg>,
  plus: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>,
  grid: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>,
  users: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2 21a7 7 0 0114 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14a6 6 0 016 5"/></svg>,
  inbox: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 13l3-8h12l3 8M3 13v6h18v-6M3 13h5l1 3h6l1-3h5"/></svg>,
  chart: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21V3M3 21h18M7 17v-6M12 17v-9M17 17v-4"/></svg>,
  settings: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 00-.1-1.4l2-1.5-2-3.4-2.3.9a7 7 0 00-2.4-1.4L13.7 3h-3.4l-.5 2.2a7 7 0 00-2.4 1.4l-2.3-.9-2 3.4 2 1.5A7 7 0 005 12c0 .5 0 1 .1 1.4l-2 1.5 2 3.4 2.3-.9a7 7 0 002.4 1.4l.5 2.2h3.4l.5-2.2a7 7 0 002.4-1.4l2.3.9 2-3.4-2-1.5c.1-.4.1-.9.1-1.4z"/></svg>,
  zap: (p) => <svg width={p?.s||16} height={p?.s||16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></svg>,
  trend: (p) => <svg width={p?.s||14} height={p?.s||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>,
  copy: (p) => <svg width={p?.s||14} height={p?.s||14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg>,
};

// Repeated diagonal watermark overlay
const Watermark = ({ text = 'RUNFOTO • MARATÓN GUATEMALA 2026', rotate = -30, opacity = 0.18, size = 12 }) => (
  <div style={{
    position: 'absolute', inset: '-20%',
    transform: `rotate(${rotate}deg)`,
    transformOrigin: 'center',
    pointerEvents: 'none',
    display: 'flex', flexDirection: 'column',
    justifyContent: 'space-between',
    overflow: 'hidden',
  }}>
    {Array.from({ length: 14 }).map((_, i) => (
      <div key={i} style={{
        fontFamily: "'Space Grotesk', sans-serif",
        fontWeight: 700,
        fontSize: size,
        color: `rgba(255,255,255,${opacity})`,
        letterSpacing: '0.3em',
        whiteSpace: 'nowrap',
        marginLeft: (i % 2) * -80,
      }}>
        {(text + ' • ').repeat(6)}
      </div>
    ))}
  </div>
);

// Phone shell — minimal, content-first
const Phone = ({ children, w = 390, h = 844, style = {} }) => (
  <div className="rf" style={{
    width: w, height: h, background: 'var(--bg)', color: 'var(--text-1)',
    overflow: 'hidden', position: 'relative', fontFamily: 'var(--body)',
    ...style,
  }}>
    {/* status bar */}
    <div style={{
      height: 44, display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', padding: '0 22px',
      fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 600,
      color: '#FAFAFA',
    }}>
      <span>9:41</span>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ width: 16, height: 10, border: '1px solid #FAFAFA', borderRadius: 2, position: 'relative' }}>
          <span style={{ position: 'absolute', inset: 1, background: '#FAFAFA', width: '70%' }} />
        </span>
      </div>
    </div>
    {children}
  </div>
);

// Desktop shell
const Desk = ({ children, w = 1440, h = 900, style = {} }) => (
  <div className="rf" style={{
    width: w, height: h, background: 'var(--bg)', color: 'var(--text-1)',
    overflow: 'hidden', position: 'relative', fontFamily: 'var(--body)',
    ...style,
  }}>{children}</div>
);

Object.assign(window, { Wordmark, PhotoPH, RunnerPH, Bib, Pill, CTA, Ghost, I, Watermark, Phone, Desk });
