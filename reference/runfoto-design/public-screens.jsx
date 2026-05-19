/* RunFoto — Public screens (1–6, 12) */

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 1 — Landing (mobile)
// ─────────────────────────────────────────────────────────────────────────
const S1_Mobile = () => (
  <Phone>
    <div data-screen-label="01 Landing — Mobile" style={{ overflow: 'auto', height: 'calc(100% - 44px)' }}>
      {/* Top brand row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 22px' }}>
        <Wordmark size={20} />
        <span className="rf-num" style={{ color: 'var(--text-3)', fontSize: 11, letterSpacing: '0.08em' }}>v2.4</span>
      </div>

      {/* Hero */}
      <div style={{
        margin: '8px 16px 0', borderRadius: 24, padding: '40px 22px 28px',
        background: 'linear-gradient(180deg, #131316 0%, #0a0a0b 100%)',
        border: '1px solid #1f1f23', position: 'relative', overflow: 'hidden',
      }}>
        <div style={{ position: 'absolute', inset: 0, opacity: 0.5, background: 'radial-gradient(60% 40% at 20% 0%, rgba(252,82,0,0.10), transparent 60%)' }} />
        <div style={{ position: 'relative' }}>
          <Pill tone="cyan" dot>EN VIVO · 3 EVENTOS</Pill>
          <h1 style={{
            fontFamily: "'Space Grotesk', sans-serif",
            fontWeight: 800, fontSize: 56, lineHeight: 0.92, letterSpacing: '-0.04em',
            margin: '16px 0 12px', color: '#FAFAFA',
          }}>
            Encontrá<br/>tus fotos<br/>de carrera.
          </h1>
          <p style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--text-2)', margin: '0 0 24px', maxWidth: 280 }}>
            Buscá por dorsal o selfie. Descargá gratis en alta resolución.
          </p>

          {/* Search input */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
              background: '#0e0e10', border: '1px solid #2a2a2e',
              borderRadius: 10, padding: '14px 14px',
            }}>
              <span style={{ color: '#00D4FF', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 14 }}>#</span>
              <input placeholder="Ingresá tu número de dorsal" style={{
                background: 'transparent', border: 'none', outline: 'none',
                color: '#FAFAFA', fontSize: 14, flex: 1, fontFamily: "'Inter', sans-serif",
              }} />
            </div>
            <CTA full size="lg" icon={<I.search s={16}/>}>Buscar fotos</CTA>
          </div>
        </div>
      </div>

      {/* Value props */}
      <div style={{ padding: '28px 22px 0', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {[
          { i: <I.bib s={18}/>, t: 'Por dorsal', s: 'OCR automático' },
          { i: <I.face s={18}/>, t: 'Por selfie', s: 'Reconocimiento facial' },
          { i: <I.download s={18}/>, t: 'Descarga gratis', s: 'Sin marca de agua' },
          { i: <I.hires s={18}/>, t: 'Alta resolución', s: 'Hasta 24 MP' },
        ].map((v, idx) => (
          <div key={idx} style={{
            background: '#17171A', border: '1px solid #2a2a2e',
            borderRadius: 12, padding: '16px 14px',
          }}>
            <div style={{ color: 'var(--text-2)', marginBottom: 10 }}>{v.i}</div>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#FAFAFA', marginBottom: 2 }}>{v.t}</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{v.s}</div>
          </div>
        ))}
      </div>

      {/* Upcoming events */}
      <div style={{ padding: '28px 22px 0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
          <h2 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 18, margin: 0 }}>Próximos eventos</h2>
          <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)' }}>3 / 12</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            { name: 'Maratón Guatemala', date: '15 NOV 2026', n: '4,327', live: true, seed: 2 },
            { name: 'Trail Antigua 21K', date: '22 NOV 2026', n: '1,842', live: false, seed: 4 },
            { name: 'Ultra Atitlán 50K', date: '06 DIC 2026', n: '928', live: false, seed: 6 },
          ].map((e, i) => (
            <div key={i} style={{ background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ position: 'relative', height: 120 }}>
                <PhotoPH seed={e.seed} label={`HERO · ${e.name.toUpperCase()}`} />
                {e.live && (
                  <div style={{ position: 'absolute', top: 10, left: 10 }}>
                    <Pill tone="cyan" dot="pulse">EN VIVO</Pill>
                  </div>
                )}
                <div style={{ position: 'absolute', bottom: 10, right: 10 }}>
                  <span className="rf-num" style={{ fontSize: 11, color: '#00D4FF', background: 'rgba(0,0,0,0.5)', padding: '4px 8px', borderRadius: 6, backdropFilter: 'blur(8px)' }}>
                    {e.n} FOTOS
                  </span>
                </div>
              </div>
              <div style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 15 }}>{e.name}</div>
                  <div className="rf-num" style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2, letterSpacing: '0.08em' }}>{e.date}</div>
                </div>
                <I.right s={18} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div style={{ padding: '32px 22px 28px', marginTop: 16, borderTop: '1px solid #1f1f23' }}>
        <Wordmark size={16} />
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 10, lineHeight: 1.6 }}>
          Plataforma gratuita de fotos de carrera.<br/>
          Sin cuentas. Sin costo. Solo tus fotos.
        </div>
        <div className="rf-num" style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 12, letterSpacing: '0.1em' }}>
          © 2026 · GUATEMALA
        </div>
      </div>
    </div>
  </Phone>
);

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 1 — Landing (desktop)
// ─────────────────────────────────────────────────────────────────────────
const S1_Desktop = () => (
  <Desk h={900} data-screen-label="01 Landing — Desktop">
    {/* Top nav */}
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 56px', borderBottom: '1px solid #1f1f23' }}>
      <Wordmark size={22} />
      <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
        <a style={{ fontSize: 13, color: 'var(--text-2)' }}>Eventos</a>
        <a style={{ fontSize: 13, color: 'var(--text-2)' }}>Cómo funciona</a>
        <a style={{ fontSize: 13, color: 'var(--text-2)' }}>Fotógrafos</a>
        <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', letterSpacing: '0.08em', borderLeft: '1px solid #2a2a2e', paddingLeft: 24 }}>ES · GT</span>
      </div>
    </div>

    {/* Hero */}
    <div style={{ padding: '56px 56px 40px', display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 56, alignItems: 'center' }}>
      <div>
        <Pill tone="cyan" dot="pulse" size="md">3 EVENTOS EN VIVO AHORA</Pill>
        <h1 style={{
          fontFamily: "'Space Grotesk', sans-serif",
          fontWeight: 800, fontSize: 96, lineHeight: 0.9, letterSpacing: '-0.04em',
          margin: '20px 0 18px', color: '#FAFAFA',
        }}>
          Encontrá<br/>tus fotos.
        </h1>
        <p style={{ fontSize: 17, lineHeight: 1.5, color: 'var(--text-2)', maxWidth: 460, margin: '0 0 32px' }}>
          Buscá tus fotos de carrera por número de dorsal o por selfie.
          Descargá en alta resolución, sin costo y sin cuenta.
        </p>
        <div style={{ display: 'flex', gap: 12, maxWidth: 540 }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', gap: 12,
            background: '#0e0e10', border: '1px solid #2a2a2e', borderRadius: 10, padding: '16px 18px',
          }}>
            <span style={{ color: '#00D4FF', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 16 }}>#</span>
            <input placeholder="Ingresá tu número de dorsal" style={{
              background: 'transparent', border: 'none', outline: 'none',
              color: '#FAFAFA', fontSize: 15, flex: 1, fontFamily: "'Inter', sans-serif",
            }} />
          </div>
          <CTA size="lg" icon={<I.search s={16}/>}>Buscar fotos</CTA>
        </div>
        <div style={{ display: 'flex', gap: 28, marginTop: 28 }}>
          <div>
            <div className="rf-num" style={{ fontSize: 22, color: '#FAFAFA', fontWeight: 600 }}>4,327</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: 2 }}>Fotos hoy</div>
          </div>
          <div style={{ width: 1, background: '#2a2a2e' }} />
          <div>
            <div className="rf-num" style={{ fontSize: 22, color: '#FAFAFA', fontWeight: 600 }}>21K</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: 2 }}>Corredores</div>
          </div>
          <div style={{ width: 1, background: '#2a2a2e' }} />
          <div>
            <div className="rf-num" style={{ fontSize: 22, color: '#FAFAFA', fontWeight: 600 }}>8</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: 2 }}>Fotógrafos</div>
          </div>
        </div>
      </div>

      {/* Hero image collage */}
      <div style={{ borderRadius: 24, overflow: 'hidden', height: 520, border: '1px solid #2a2a2e', display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 2, background: '#0a0a0b' }}>
        <div style={{ position: 'relative' }}>
          <PhotoPH seed={3} label="HERO · CORREDOR · 4:5" />
          <div style={{ position: 'absolute', bottom: 14, left: 14 }}>
            <Bib n="#1042" size="md" />
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateRows: '1fr 1fr', gap: 2 }}>
          <PhotoPH seed={5} label="DETALLE" />
          <PhotoPH seed={7} label="META" />
        </div>
      </div>
    </div>

    {/* Value props */}
    <div style={{ padding: '12px 56px 0', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
      {[
        { i: <I.bib s={20}/>, t: 'Búsqueda por dorsal', s: 'OCR automático sobre cada foto.' },
        { i: <I.face s={20}/>, t: 'Reconocimiento facial', s: 'Subí una selfie, te encontramos.' },
        { i: <I.download s={20}/>, t: 'Descarga gratis', s: 'Sin marca de agua, sin costo.' },
        { i: <I.hires s={20}/>, t: 'Alta resolución', s: 'Archivo original del fotógrafo.' },
      ].map((v, idx) => (
        <div key={idx} style={{ background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 12, padding: '20px 20px' }}>
          <div style={{ color: '#00D4FF', marginBottom: 14 }}>{v.i}</div>
          <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6 }}>{v.t}</div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.45 }}>{v.s}</div>
        </div>
      ))}
    </div>
  </Desk>
);

// ─────────────────────────────────────────────────────────────────────────
// Shared gallery header (used by Screens 2, 3, 4, 12)
// ─────────────────────────────────────────────────────────────────────────
const EventHero = ({ light = false }) => {
  const bg = light ? '#FFFFFF' : '#0A0A0B';
  const text = light ? '#0A0A0B' : '#FAFAFA';
  const sub = light ? '#6B6B70' : '#A1A1A6';
  const border = light ? '#E5E5E7' : '#1f1f23';
  return (
    <div style={{ position: 'relative', borderBottom: `1px solid ${border}` }}>
      <div style={{
        height: 220, position: 'relative', overflow: 'hidden',
        background: light
          ? 'linear-gradient(180deg, #f4f4f6 0%, #fafafa 100%)'
          : 'linear-gradient(180deg, #1a1418 0%, #0a0a0b 100%)',
      }}>
        <PhotoPH seed={2} label="" style={{ position: 'absolute', inset: 0, opacity: light ? 0.18 : 0.35 }} />
        <div style={{
          position: 'absolute', inset: 0,
          background: light
            ? 'linear-gradient(180deg, rgba(255,255,255,0.2) 0%, rgba(250,250,250,0.95) 100%)'
            : 'linear-gradient(180deg, rgba(10,10,11,0.4) 0%, rgba(10,10,11,0.95) 100%)',
        }} />
        <div style={{ position: 'relative', padding: '36px 40px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <Pill tone="cyan" dot="pulse" size="md">EN VIVO</Pill>
            <span className="rf-num" style={{ fontSize: 10, color: sub, letterSpacing: '0.1em' }}>15 NOV 2026 · GUATEMALA</span>
          </div>
          <h1 style={{
            fontFamily: "'Space Grotesk', sans-serif",
            fontWeight: 900, fontSize: 64, lineHeight: 0.9, letterSpacing: '-0.04em',
            margin: 0, color: text, textTransform: 'uppercase',
          }}>Maratón<br/>Guatemala 2026</h1>
          <div style={{ marginTop: 18, display: 'flex', alignItems: 'center', gap: 22, color: sub }}>
            <span className="rf-num" style={{ fontSize: 12 }}><span style={{ color: text }}>4,327</span> fotos</span>
            <span style={{ width: 3, height: 3, borderRadius: 99, background: sub }} />
            <span className="rf-num" style={{ fontSize: 12 }}><span style={{ color: text }}>8</span> fotógrafos</span>
            <span style={{ width: 3, height: 3, borderRadius: 99, background: sub }} />
            <span className="rf-num" style={{ fontSize: 12 }}><span style={{ color: text }}>21K</span> participantes</span>
          </div>
        </div>
      </div>
    </div>
  );
};

const SearchBar = ({ light = false, tab = 'bib', value = '', selfie = false, matches = null }) => {
  const bg = light ? '#FFFFFF' : '#0A0A0B';
  const surf = light ? '#FAFAFA' : '#0e0e10';
  const text = light ? '#0A0A0B' : '#FAFAFA';
  const sub = light ? '#6B6B70' : '#A1A1A6';
  const border = light ? '#E5E5E7' : '#2a2a2e';
  return (
    <div style={{ background: bg, borderBottom: `1px solid ${border}`, padding: '0 40px' }}>
      <div style={{ display: 'flex', gap: 28, borderBottom: `1px solid ${border}` }}>
        {[['bib', 'Por dorsal'], ['selfie', 'Por selfie']].map(([k, label]) => (
          <button key={k} className="rf-cta" style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '14px 0',
            fontSize: 11, letterSpacing: '0.08em',
            color: tab === k ? '#FC5200' : sub,
            borderBottom: tab === k ? '2px solid #FC5200' : '2px solid transparent',
            marginBottom: -1,
          }}>{label}</button>
        ))}
      </div>
      <div style={{ padding: '14px 0', display: 'flex', alignItems: 'center', gap: 12 }}>
        {selfie ? (
          <>
            <div style={{
              width: 36, height: 36, borderRadius: 99, overflow: 'hidden',
              border: `1px solid ${border}`, position: 'relative', flexShrink: 0,
            }}>
              <PhotoPH seed={3} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, color: text, fontWeight: 500 }}>selfie.jpg</div>
              <div className="rf-num" style={{ fontSize: 11, color: '#00D4FF', marginTop: 2 }}>{matches} coincidencias encontradas</div>
            </div>
            <Ghost size="sm">Cambiar foto</Ghost>
          </>
        ) : (
          <>
            <div style={{
              flex: 1, display: 'flex', alignItems: 'center', gap: 10,
              background: surf, border: `1px solid ${border}`, borderRadius: 8, padding: '10px 14px',
            }}>
              <span style={{ color: '#00D4FF', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 14 }}>#</span>
              <input value={value} readOnly placeholder="Ingresá tu número de dorsal" style={{
                background: 'transparent', border: 'none', outline: 'none',
                color: text, fontSize: 14, flex: 1,
                fontFamily: value ? "'JetBrains Mono', monospace" : "'Inter', sans-serif",
                fontWeight: value ? 600 : 400, letterSpacing: value ? '0.05em' : 0,
              }} />
            </div>
            <CTA size="md" icon={<I.search s={14}/>}>Buscar</CTA>
          </>
        )}
      </div>
    </div>
  );
};

// Photo grid item — for screens 2, 3, 12
const PhotoCell = ({ seed, bib, selected, badge, badgeTone, light, aspect = '4/5' }) => {
  const orange = '#FC5200';
  return (
    <div style={{ position: 'relative', aspectRatio: aspect, background: light ? '#f0f0f2' : '#0e0e10' }}>
      <PhotoPH seed={seed} label={`#${bib}`} />
      {/* selection outline */}
      {selected && (
        <div style={{ position: 'absolute', inset: 0, boxShadow: `inset 0 0 0 3px ${orange}`, pointerEvents: 'none' }} />
      )}
      {/* bib */}
      <div style={{ position: 'absolute', bottom: 8, left: 8 }}>
        <Bib n={`#${bib}`} />
      </div>
      {/* checkbox top-right */}
      {selected !== undefined && (
        <div style={{
          position: 'absolute', top: 8, right: 8,
          width: 20, height: 20, borderRadius: 4,
          background: selected ? orange : 'rgba(10,10,11,0.55)',
          border: selected ? 'none' : `1px solid ${light ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.5)'}`,
          backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff',
        }}>
          {selected && <I.check s={12}/>}
        </div>
      )}
      {/* confidence badge top-left */}
      {badge && (
        <div style={{ position: 'absolute', top: 8, left: 8 }}>
          <Pill tone={badgeTone} size="sm">{badge}</Pill>
        </div>
      )}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 2 — Event gallery, bib search active (★ main)
// ─────────────────────────────────────────────────────────────────────────
const S2_GalleryBib = ({ light = false }) => {
  const bg = light ? '#FAFAFA' : '#0A0A0B';
  const text = light ? '#0A0A0B' : '#FAFAFA';
  const border = light ? '#E5E5E7' : '#2A2A2E';
  // 16 cells — selected: 2, 6, 11
  const cells = Array.from({ length: 16 }).map((_, i) => ({
    seed: i, bib: 1040 + i * 3,
    selected: [2, 6, 11].includes(i),
  }));

  return (
    <Desk h={1200} data-screen-label={light ? '12 Gallery Light' : '02 Gallery — Bib'} style={{ background: bg, color: text }}>
      {/* mini top */}
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 40px', borderBottom: `1px solid ${border}`, background: bg }}>
        <Wordmark size={18} color={text} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 12, color: light ? '#6B6B70' : '#A1A1A6' }}>
          <span>← Volver a eventos</span>
        </div>
      </div>

      <EventHero light={light} />

      <div style={{ position: 'sticky', top: 0, zIndex: 5 }}>
        <SearchBar light={light} tab="bib" value="1042" />
      </div>

      {/* Filters strip */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 40px', borderBottom: `1px solid ${border}` }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Pill tone="orange" size="md">Dorsal #1042 · 16 fotos</Pill>
          <Pill tone="neutral" size="md">Todos los fotógrafos</Pill>
          <Pill tone="neutral" size="md">Todo el día</Pill>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, color: light ? '#6B6B70' : '#A1A1A6', fontSize: 12 }}>
          <span>Ordenar por</span>
          <span style={{ color: text, fontWeight: 500 }}>Hora ▾</span>
          <div style={{ width: 1, height: 16, background: border }} />
          <div style={{ display: 'flex', gap: 4 }}>
            <button style={{ width: 28, height: 28, background: light ? '#0a0a0b' : '#1f1f23', border: 'none', color: light ? '#FAFAFA' : '#FAFAFA', borderRadius: 6, display: 'grid', placeItems: 'center' }}>
              <I.grid s={14}/>
            </button>
          </div>
        </div>
      </div>

      {/* Photo grid */}
      <div style={{ padding: 0, background: light ? '#E5E5E7' : '#0a0a0b' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 2 }}>
          {cells.map((c, i) => (
            <PhotoCell key={i} seed={c.seed} bib={c.bib} selected={c.selected} light={light} />
          ))}
        </div>
      </div>

      {/* Floating selection pill */}
      <div style={{
        position: 'absolute', bottom: 28, left: '50%', transform: 'translateX(-50%)',
        background: light ? '#0A0A0B' : '#17171A',
        border: `1px solid ${light ? '#0A0A0B' : '#2A2A2E'}`,
        borderRadius: 999, padding: '8px 8px 8px 22px',
        display: 'flex', alignItems: 'center', gap: 18,
        color: light ? '#FAFAFA' : '#FAFAFA',
      }}>
        <span className="rf-num" style={{ fontSize: 13, fontWeight: 600 }}>3 fotos seleccionadas</span>
        <span style={{ width: 1, height: 18, background: '#2a2a2e' }} />
        <span style={{ fontSize: 12, color: '#A1A1A6' }}>~ 14.2 MB</span>
        <CTA size="sm" icon={<I.download s={14}/>}>Descargar</CTA>
      </div>
    </Desk>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 3 — Event gallery, selfie search
// ─────────────────────────────────────────────────────────────────────────
const S3_GallerySelfie = () => {
  const cells = [
    { seed: 1, bib: 1042, c: '95%', t: 'green' },
    { seed: 3, bib: 1042, c: '94%', t: 'green' },
    { seed: 5, bib: 1042, c: '91%', t: 'green' },
    { seed: 2, bib: 1042, c: '88%', t: 'cyan' },
    { seed: 7, bib: 1042, c: '85%', t: 'cyan' },
    { seed: 4, bib: 1042, c: '82%', t: 'cyan' },
    { seed: 6, bib: 1042, c: '78%', t: 'cyan' },
    { seed: 0, bib: 1042, c: '76%', t: 'cyan' },
    { seed: 1, bib: 1042, c: '73%', t: 'amber' },
    { seed: 3, bib: 1042, c: '69%', t: 'amber' },
    { seed: 5, bib: 1042, c: '64%', t: 'amber' },
    { seed: 2, bib: 1042, c: '61%', t: 'amber' },
  ];
  return (
    <Desk h={1100} data-screen-label="03 Gallery — Selfie">
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 40px', borderBottom: '1px solid #2a2a2e' }}>
        <Wordmark size={18} />
        <span style={{ fontSize: 12, color: 'var(--text-2)' }}>← Volver a eventos</span>
      </div>
      <EventHero />
      <SearchBar tab="selfie" selfie matches={12} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 40px', borderBottom: '1px solid #2a2a2e' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Pill tone="green" size="md">3 alta confianza</Pill>
          <Pill tone="cyan" size="md">5 confianza media</Pill>
          <Pill tone="amber" size="md">4 confianza baja</Pill>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, color: 'var(--text-2)', fontSize: 12 }}>
          <span>Ordenar por</span>
          <span style={{ color: '#FAFAFA', fontWeight: 500 }}>Confianza ▾</span>
        </div>
      </div>
      <div style={{ padding: 0, background: '#0a0a0b' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 2 }}>
          {cells.map((c, i) => (
            <PhotoCell key={i} seed={c.seed + i} bib={c.bib} badge={c.c} badgeTone={c.t} />
          ))}
        </div>
      </div>
    </Desk>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 4 — Empty state
// ─────────────────────────────────────────────────────────────────────────
const S4_Empty = () => (
  <Desk h={900} data-screen-label="04 Empty state">
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 40px', borderBottom: '1px solid #2a2a2e' }}>
      <Wordmark size={18} />
      <span style={{ fontSize: 12, color: 'var(--text-2)' }}>← Volver a eventos</span>
    </div>
    <EventHero />
    <SearchBar tab="bib" value="5512" />
    <div style={{ padding: '64px 40px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
      <div style={{
        width: 96, height: 96, borderRadius: 99,
        background: 'rgba(0,212,255,0.08)',
        border: '1px solid rgba(0,212,255,0.15)',
        display: 'grid', placeItems: 'center', position: 'relative', marginBottom: 24,
        color: '#00D4FF',
      }}>
        <I.search s={36} />
        <span className="rf-num" style={{
          position: 'absolute', top: -6, right: -6,
          background: '#1f1f23', border: '1px solid #2a2a2e',
          borderRadius: 99, width: 30, height: 30, display: 'grid', placeItems: 'center',
          fontSize: 12, fontWeight: 600, color: '#FAFAFA',
        }}>0</span>
      </div>
      <h2 style={{
        fontFamily: "'Space Grotesk', sans-serif", fontWeight: 800,
        fontSize: 28, letterSpacing: '-0.02em', margin: 0, maxWidth: 540,
      }}>
        No encontramos fotos para el dorsal <span style={{ color: '#00D4FF', fontFamily: "'JetBrains Mono', monospace" }}>#5512</span>
      </h2>
      <p style={{ fontSize: 14, color: 'var(--text-2)', marginTop: 12, maxWidth: 480, lineHeight: 1.5 }}>
        Los fotógrafos todavía pueden estar subiendo fotos del evento. Probá de nuevo en unos minutos o buscá con tu selfie.
      </p>
      <div style={{ display: 'flex', gap: 12, marginTop: 26 }}>
        <CTA size="md" icon={<I.face s={14}/>}>Buscar con selfie</CTA>
        <Ghost size="md">Volver a la galería</Ghost>
      </div>

      {/* OCR suggestion card */}
      <div style={{
        marginTop: 40, background: '#17171A', border: '1px solid #2a2a2e',
        borderRadius: 12, padding: '18px 22px', maxWidth: 480, textAlign: 'left', width: '100%',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <Pill tone="amber" size="sm">OCR</Pill>
          <span style={{ fontSize: 13, fontWeight: 500 }}>¿Quizá quisiste decir...?</span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 14 }}>
          Estos dorsales tienen lectura similar y fueron detectados en este evento:
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['5152', '5212', '5513'].map((n) => (
            <button key={n} className="rf-num" style={{
              padding: '10px 16px', borderRadius: 8, cursor: 'pointer',
              background: '#0e0e10', border: '1px solid rgba(0,212,255,0.25)',
              color: '#00D4FF', fontWeight: 600, fontSize: 14,
              letterSpacing: '0.05em',
            }}>#{n}</button>
          ))}
        </div>
      </div>
    </div>
  </Desk>
);

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 5 — Lightbox modal
// ─────────────────────────────────────────────────────────────────────────
const S5_Lightbox = () => (
  <Desk h={900} data-screen-label="05 Lightbox" style={{ background: '#050506' }}>
    {/* Top bar */}
    <div style={{
      position: 'absolute', top: 0, left: 0, right: 0, zIndex: 3,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '20px 32px',
      background: 'linear-gradient(180deg, rgba(0,0,0,0.7), transparent)',
    }}>
      <button style={{ background: 'transparent', border: 'none', color: '#FAFAFA', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10 }}>
        <I.close s={22}/>
        <span style={{ fontSize: 13 }}>Cerrar</span>
      </button>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span className="rf-num" style={{ color: '#FAFAFA', fontSize: 13, fontWeight: 600 }}>12 <span style={{ color: 'var(--text-3)' }}>/ 4,327</span></span>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button style={{ width: 36, height: 36, borderRadius: 8, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.share s={16}/></button>
        <button style={{ width: 36, height: 36, borderRadius: 8, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.download s={16}/></button>
        <button style={{ width: 36, height: 36, borderRadius: 8, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.more s={16}/></button>
      </div>
    </div>

    {/* Photo */}
    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '76px 100px 100px' }}>
      <div style={{ position: 'relative', aspectRatio: '4/5', height: '100%', borderRadius: 4, overflow: 'hidden' }}>
        <PhotoPH seed={3} label="" />
        <Watermark text="RUNFOTO • MARATÓN GUATEMALA 2026" rotate={-30} opacity={0.16} size={14} />
      </div>
    </div>

    {/* Left/right arrows */}
    <button style={{ position: 'absolute', left: 24, top: '50%', transform: 'translateY(-50%)', width: 48, height: 48, borderRadius: 99, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.left s={20}/></button>
    <button style={{ position: 'absolute', right: 24, top: '50%', transform: 'translateY(-50%)', width: 48, height: 48, borderRadius: 99, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.right s={20}/></button>

    {/* Bottom bar */}
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 3,
      padding: '24px 32px',
      background: 'linear-gradient(0deg, rgba(0,0,0,0.75), transparent)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <Bib n="#1042" size="lg" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="rf-num" style={{ fontSize: 12, color: 'var(--text-2)', letterSpacing: '0.08em' }}>15 NOV 2026 · 09:24 AM</span>
          <span style={{ fontSize: 13, color: '#FAFAFA' }}>Marcus Volt · <span style={{ color: 'var(--text-3)' }}>Fotógrafo oficial</span></span>
        </div>
      </div>
      <CTA size="md" icon={<I.download s={14}/>}>Descargar esta foto</CTA>
    </div>
  </Desk>
);

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 6 — Multi-select download bottom sheet (mobile)
// ─────────────────────────────────────────────────────────────────────────
const S6_DownloadSheet = () => (
  <Phone>
    <div data-screen-label="06 Download sheet" style={{ position: 'relative', height: 'calc(100% - 44px)' }}>
      {/* dimmed gallery behind */}
      <div style={{ position: 'absolute', inset: 0, filter: 'blur(6px) brightness(0.5)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, padding: 8 }}>
          {Array.from({ length: 14 }).map((_, i) => (
            <div key={i} style={{ aspectRatio: '4/5' }}>
              <PhotoPH seed={i} />
            </div>
          ))}
        </div>
      </div>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,11,0.5)' }} />

      {/* sheet */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        background: '#0e0e10', borderTop: '1px solid #2a2a2e',
        borderTopLeftRadius: 20, borderTopRightRadius: 20,
        padding: '14px 22px 28px',
      }}>
        <div style={{ width: 36, height: 4, background: '#2a2a2e', borderRadius: 99, margin: '0 auto 16px' }} />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 4 }}>
          <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 24, margin: 0, letterSpacing: '-0.02em' }}>
            12 fotos seleccionadas
          </h3>
        </div>
        <div className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', marginBottom: 18, letterSpacing: '0.08em' }}>
          58 MB · Se descargará como ZIP
        </div>

        {/* Thumbnail row */}
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', marginBottom: 22, paddingBottom: 4 }}>
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} style={{ position: 'relative', flexShrink: 0, width: 64, height: 80, borderRadius: 6, overflow: 'hidden' }}>
              <PhotoPH seed={i+1} />
              <button style={{
                position: 'absolute', top: 4, right: 4, width: 18, height: 18, borderRadius: 99,
                background: 'rgba(0,0,0,0.7)', border: 'none', color: '#fff',
                display: 'grid', placeItems: 'center', cursor: 'pointer',
              }}><I.close s={10}/></button>
            </div>
          ))}
        </div>

        <CTA full size="lg" icon={<I.download s={16}/>}>Descargar ZIP</CTA>
        <div style={{ height: 10 }} />
        <Ghost full size="md">Cancelar</Ghost>

        <div style={{
          marginTop: 16, padding: '10px 12px', background: '#17171A', border: '1px solid #2a2a2e',
          borderRadius: 8, display: 'flex', alignItems: 'center', gap: 10,
          fontSize: 11, color: 'var(--text-2)',
        }}>
          <span style={{ color: '#10B981' }}><I.check s={14}/></span>
          La descarga en alta resolución no tiene marca de agua
        </div>
      </div>
    </div>
  </Phone>
);

Object.assign(window, { S1_Mobile, S1_Desktop, S2_GalleryBib, S3_GallerySelfie, S4_Empty, S5_Lightbox, S6_DownloadSheet });
