/* RunFoto — Screen 7: Photographer upload portal (NO sidebar, single-page) */

const S7_PhotographerPortal = () => {
  const queue = [
    { name: 'IMG_0247.jpg', prog: 0.62, status: 'Subiendo', tone: 'orange', size: '12.4 MB', seed: 1 },
    { name: 'IMG_0246.jpg', prog: 1.0, status: 'Procesando OCR + Faces', tone: 'cyan', size: '11.8 MB', seed: 2 },
    { name: 'IMG_0245.jpg', prog: 1.0, status: 'Procesando OCR + Faces', tone: 'cyan', size: '14.1 MB', seed: 3 },
    { name: 'IMG_0244.jpg', prog: 1.0, status: 'Lista', tone: 'green', size: '13.2 MB', seed: 4 },
    { name: 'IMG_0243.jpg', prog: 1.0, status: 'Lista', tone: 'green', size: '10.7 MB', seed: 5 },
  ];

  return (
    <Desk h={1200} data-screen-label="07 Photographer portal">
      {/* Minimal top header — wordmark + small label, no nav */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '20px 56px', borderBottom: '1px solid #1f1f23',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <Wordmark size={20} />
          <span style={{ width: 1, height: 18, background: '#2a2a2e' }} />
          <span className="rf-cta" style={{ fontSize: 11, color: 'var(--text-2)' }}>PORTAL DE SUBIDA</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Pill tone="amber" dot size="sm">SESIÓN DE TOKEN</Pill>
          <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', letterSpacing: '0.08em' }}>u/abc123x</span>
        </div>
      </div>

      {/* Context strip */}
      <div style={{ padding: '40px 56px 32px', borderBottom: '1px solid #1f1f23' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 14 }}>
          <span className="rf-cta" style={{ fontSize: 10, color: 'var(--text-3)' }}>FOTÓGRAFO</span>
          <span style={{ fontSize: 15, fontWeight: 500 }}>Juan Pérez</span>
          <span style={{ color: 'var(--text-3)', fontSize: 13 }}>·</span>
          <span style={{ fontSize: 13, color: 'var(--text-2)' }}>juan@volt.gt</span>
        </div>
        <h1 style={{
          fontFamily: "'Space Grotesk', sans-serif", fontWeight: 900,
          fontSize: 72, letterSpacing: '-0.04em', lineHeight: 0.92,
          margin: '0 0 22px', textTransform: 'uppercase',
        }}>
          Maratón<br/>Guatemala 2026
        </h1>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <Pill tone="neutral" size="md"><I.calendar s={12}/> 15 NOV 2026</Pill>
          <Pill tone="amber" size="md"><I.clock s={12}/> LINK VÁLIDO HASTA 30 NOV</Pill>
          <Pill tone="cyan" size="md"><I.camera s={12}/> 247 FOTOS SUBIDAS</Pill>
        </div>
      </div>

      {/* Dropzone */}
      <div style={{ padding: '32px 56px 0' }}>
        <div style={{
          border: '2px dashed #2a2a2e', borderRadius: 16,
          padding: '52px 32px', textAlign: 'center', position: 'relative',
          background: 'radial-gradient(60% 60% at 50% 0%, rgba(0,212,255,0.04), transparent 70%)',
        }}>
          <div style={{ display: 'inline-grid', placeItems: 'center', width: 64, height: 64, borderRadius: 99, background: 'rgba(0,212,255,0.10)', color: '#00D4FF', marginBottom: 18 }}>
            <I.upload s={28}/>
          </div>
          <h2 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 28, margin: '0 0 8px', letterSpacing: '-0.02em' }}>
            Arrastrá tus fotos acá
          </h2>
          <div className="rf-num" style={{ fontSize: 12, color: 'var(--text-3)', letterSpacing: '0.06em' }}>
            Solo JPG · Máximo 15 MB por foto · Sin límite de cantidad
          </div>
          <div style={{ marginTop: 22 }}>
            <CTA size="md">Seleccionar archivos</CTA>
          </div>
        </div>
      </div>

      {/* Upload queue */}
      <div style={{ padding: '32px 56px 0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
          <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 17, margin: 0 }}>Cola de subida</h3>
          <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)' }}>5 archivos · 62.2 MB</span>
        </div>
        <div style={{ background: '#0e0e10', border: '1px solid #2a2a2e', borderRadius: 12, overflow: 'hidden' }}>
          {queue.map((q, i) => (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '52px 1fr 200px 140px 100px',
              alignItems: 'center', gap: 16,
              padding: '14px 18px',
              borderBottom: i < queue.length - 1 ? '1px solid #1f1f23' : 'none',
            }}>
              <div style={{ width: 52, height: 52, borderRadius: 6, overflow: 'hidden' }}>
                <PhotoPH seed={q.seed} />
              </div>
              <div>
                <div className="rf-num" style={{ fontSize: 13, fontWeight: 500 }}>{q.name}</div>
                <div className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{q.size}</div>
              </div>
              <div style={{ height: 6, borderRadius: 99, background: '#1f1f23', overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${q.prog * 100}%`,
                  background: q.tone === 'orange' ? '#FC5200' : q.tone === 'cyan' ? '#00D4FF' : '#10B981',
                  transition: 'width 0.3s',
                }} />
              </div>
              <Pill tone={q.tone} dot={q.tone === 'orange' ? 'pulse' : false} size="sm">{q.status}</Pill>
              <div style={{ textAlign: 'right', color: 'var(--text-3)', cursor: 'pointer' }}>
                <I.more s={16} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recently uploaded */}
      <div style={{ padding: '32px 56px 56px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
          <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 17, margin: 0 }}>Subidas recientes</h3>
          <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)' }}>Mostrando 12 de 247</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 4 }}>
          {Array.from({ length: 16 }).map((_, i) => (
            <div key={i} style={{ position: 'relative', aspectRatio: '4/5' }}>
              <PhotoPH seed={i + 1} />
              <div style={{ position: 'absolute', bottom: 6, left: 6 }}>
                <Bib n={`#${1040 + i*3}`} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </Desk>
  );
};

Object.assign(window, { S7_PhotographerPortal });
