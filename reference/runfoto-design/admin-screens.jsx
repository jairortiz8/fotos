/* RunFoto — Admin screens (8-11) */

// Shared admin sidebar (240px)
const AdminSidebar = ({ active = 'dashboard' }) => {
  const nav = [
    { k: 'dashboard', i: <I.grid s={16}/>, l: 'Dashboard' },
    { k: 'eventos', i: <I.calendar s={16}/>, l: 'Eventos' },
    { k: 'fotografos', i: <I.users s={16}/>, l: 'Fotógrafos' },
    { k: 'aprobacion', i: <I.inbox s={16}/>, l: 'Aprobación', badge: '23' },
    { k: 'estadisticas', i: <I.chart s={16}/>, l: 'Estadísticas' },
    { k: 'config', i: <I.settings s={16}/>, l: 'Configuración' },
  ];
  return (
    <div style={{
      width: 240, background: '#050506', borderRight: '1px solid #1f1f23',
      display: 'flex', flexDirection: 'column', height: '100%',
    }}>
      <div style={{ padding: '22px 22px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Wordmark size={18} />
        </div>
        <div className="rf-cta" style={{ fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.16em', marginTop: 6 }}>ADMIN</div>
      </div>
      <div style={{ borderTop: '1px solid #1f1f23', padding: '10px 12px', flex: 1 }}>
        {nav.map((n) => {
          const isActive = active === n.k;
          return (
            <div key={n.k} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 12px',
              fontSize: 13, fontWeight: isActive ? 600 : 400,
              color: isActive ? '#FAFAFA' : 'var(--text-2)',
              background: isActive ? '#17171A' : 'transparent',
              borderLeft: isActive ? '2px solid #FC5200' : '2px solid transparent',
              marginLeft: isActive ? -2 : 0,
              borderRadius: 6,
              cursor: 'pointer',
            }}>
              <span style={{ color: isActive ? '#FAFAFA' : 'var(--text-3)' }}>{n.i}</span>
              <span style={{ flex: 1 }}>{n.l}</span>
              {n.badge && (
                <span className="rf-num" style={{
                  padding: '2px 6px', fontSize: 10, borderRadius: 99,
                  background: '#FC5200', color: '#fff', fontWeight: 600,
                }}>{n.badge}</span>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ padding: 12, borderTop: '1px solid #1f1f23' }}>
        <CTA full size="md" icon={<I.plus s={14}/>}>Nuevo Evento</CTA>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, padding: '8px 4px' }}>
          <div style={{
            width: 32, height: 32, borderRadius: 99,
            background: 'linear-gradient(135deg, #FC5200, #b03700)',
            display: 'grid', placeItems: 'center', color: '#fff',
            fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 12,
          }}>AR</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 500 }}>Andrés Ramírez</div>
            <div className="rf-num" style={{ fontSize: 10, color: 'var(--text-3)' }}>SUPER ADMIN</div>
          </div>
        </div>
      </div>
    </div>
  );
};

const StatCard = ({ label, value, unit, delta, deltaTone = 'green' }) => (
  <div style={{ background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 12, padding: '18px 20px' }}>
    <div style={{ fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 10 }}>
      <span className="rf-num" style={{ fontSize: 30, fontWeight: 600, color: '#FAFAFA', letterSpacing: '-0.02em' }}>{value}</span>
      {unit && <span style={{ fontSize: 12, color: 'var(--text-3)', fontFamily: "'JetBrains Mono', monospace" }}>{unit}</span>}
    </div>
    {delta && (
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 10, color: deltaTone === 'green' ? '#10B981' : '#EF4444' }}>
        <I.trend s={12}/>
        <span className="rf-num" style={{ fontSize: 11, fontWeight: 500 }}>{delta}</span>
        <span style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 4 }}>vs. semana pasada</span>
      </div>
    )}
  </div>
);

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 8 — Admin dashboard
// ─────────────────────────────────────────────────────────────────────────
const S8_AdminDashboard = () => (
  <Desk h={950} data-screen-label="08 Admin dashboard">
    <div style={{ display: 'flex', height: '100%' }}>
      <AdminSidebar active="dashboard" />
      <div style={{ flex: 1, overflow: 'auto' }}>
        {/* Topbar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '22px 32px', borderBottom: '1px solid #1f1f23' }}>
          <div>
            <h1 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 24, margin: 0, letterSpacing: '-0.02em' }}>Dashboard</h1>
            <div className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4, letterSpacing: '0.06em' }}>SÁBADO · 14 NOV 2026 · 11:32 AM</div>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <Ghost size="sm">Últimos 30 días ▾</Ghost>
            <Ghost size="sm">Exportar</Ghost>
          </div>
        </div>

        <div style={{ padding: 32 }}>
          {/* Stat row */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 32 }}>
            <StatCard label="Total eventos" value="12" delta="+2 nuevos" />
            <StatCard label="Total fotos" value="18,432" delta="+1,847" />
            <StatCard label="Almacenamiento" value="68" unit="GB" delta="+8.4 GB" />
            <StatCard label="Búsquedas hoy" value="342" delta="+18%" />
          </div>

          {/* Two columns */}
          <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 24 }}>
            {/* Eventos activos */}
            <div style={{ background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '18px 22px', borderBottom: '1px solid #2a2a2e' }}>
                <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 15, margin: 0 }}>Eventos activos</h3>
                <span style={{ fontSize: 12, color: 'var(--text-2)' }}>Ver todos →</span>
              </div>
              <div>
                {[
                  { name: 'Maratón Guatemala 2026', date: '15 NOV', tone: 'cyan', label: 'EN VIVO', n: '4,327', seed: 2 },
                  { name: 'Trail Antigua 21K', date: '22 NOV', tone: 'amber', label: 'PRÓXIMO', n: '0', seed: 4 },
                  { name: 'Ultra Atitlán 50K', date: '06 DIC', tone: 'amber', label: 'PRÓXIMO', n: '0', seed: 6 },
                  { name: 'Trail Tikal Nocturno', date: '08 NOV', tone: 'neutral', label: 'CERRADO', n: '2,184', seed: 5 },
                  { name: 'Volcán Pacaya Run', date: '01 NOV', tone: 'neutral', label: 'CERRADO', n: '1,652', seed: 3 },
                ].map((e, i) => (
                  <div key={i} style={{
                    display: 'grid', gridTemplateColumns: '54px 1fr 120px 110px 70px',
                    alignItems: 'center', gap: 14,
                    padding: '14px 22px', borderBottom: i < 4 ? '1px solid #1f1f23' : 'none',
                  }}>
                    <div style={{ width: 54, height: 54, borderRadius: 6, overflow: 'hidden' }}>
                      <PhotoPH seed={e.seed} />
                    </div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{e.name}</div>
                      <div className="rf-num" style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 3, letterSpacing: '0.08em' }}>{e.date} · GUATEMALA</div>
                    </div>
                    <Pill tone={e.tone} size="sm" dot={e.tone === 'cyan' ? 'pulse' : false}>{e.label}</Pill>
                    <div className="rf-num" style={{ fontSize: 13, color: '#00D4FF', fontWeight: 600, textAlign: 'right' }}>
                      {e.n} <span style={{ color: 'var(--text-3)', fontSize: 10 }}>FOTOS</span>
                    </div>
                    <div style={{ textAlign: 'right', color: 'var(--text-3)' }}><I.right s={14}/></div>
                  </div>
                ))}
              </div>
            </div>

            {/* Pendientes */}
            <div style={{ background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '18px 22px', borderBottom: '1px solid #2a2a2e' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 15, margin: 0 }}>Pendientes</h3>
                  <span className="rf-num" style={{
                    padding: '2px 8px', fontSize: 11, borderRadius: 99,
                    background: '#FC5200', color: '#fff', fontWeight: 600,
                  }}>23</span>
                </div>
              </div>
              <div style={{ padding: 18 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginBottom: 18 }}>
                  {[1,2,3,4,5].map((s) => (
                    <div key={s} style={{ aspectRatio: '4/5', position: 'relative', overflow: 'hidden', borderRadius: 4 }}>
                      <PhotoPH seed={s + 5} />
                      <div style={{ position: 'absolute', top: 4, right: 4, width: 14, height: 14, borderRadius: 3, background: 'rgba(245,158,11,0.9)' }} />
                    </div>
                  ))}
                  <div style={{
                    aspectRatio: '4/5', display: 'grid', placeItems: 'center',
                    background: '#0e0e10', border: '1px dashed #2a2a2e', borderRadius: 4,
                  }}>
                    <span className="rf-num" style={{ fontSize: 12, color: 'var(--text-2)', fontWeight: 600 }}>+17 más</span>
                  </div>
                </div>
                <CTA full size="md">Revisar todas</CTA>
                <div style={{ marginTop: 14, fontSize: 11, color: 'var(--text-3)', textAlign: 'center' }}>
                  Antigüedad promedio: <span className="rf-num" style={{ color: 'var(--text-2)' }}>3h 12m</span>
                </div>
              </div>
            </div>
          </div>

          {/* Activity bar mini */}
          <div style={{ marginTop: 24, background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 12, padding: '18px 22px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
              <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 15, margin: 0 }}>Subidas por hora · hoy</h3>
              <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)' }}>00:00 → 11:32</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 80 }}>
              {[12,18,22,14,8,5,3,2,4,9,28,42,67,84,72,58,49,41,36,22,18,14,9,5].map((h, i) => (
                <div key={i} style={{ flex: 1, height: `${h}%`, background: i >= 11 && i <= 13 ? '#FC5200' : '#2a2a2e', borderRadius: 2 }} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  </Desk>
);

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 9 — Generate upload link modal
// ─────────────────────────────────────────────────────────────────────────

// Simple stylized QR
const QRMark = ({ size = 160 }) => {
  // 21x21 module dummy pattern w/ finder squares
  const cells = [];
  const dim = 21;
  // Build pseudo-random pattern (deterministic)
  for (let y = 0; y < dim; y++) {
    for (let x = 0; x < dim; x++) {
      const v = (x*7 + y*13 + x*y*3) % 11;
      cells.push({ x, y, on: v < 5 });
    }
  }
  // Mask out finder patterns
  const isFinder = (x, y) => (
    (x < 7 && y < 7) || (x > dim - 8 && y < 7) || (x < 7 && y > dim - 8)
  );
  const m = size / dim;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${dim} ${dim}`} style={{ background: '#fff', borderRadius: 8, padding: 4, boxSizing: 'border-box' }}>
      {/* modules */}
      {cells.map((c, i) => !isFinder(c.x, c.y) && c.on && (
        <rect key={i} x={c.x} y={c.y} width="1" height="1" fill="#0A0A0B" />
      ))}
      {/* finder squares (3) */}
      {[[0,0],[14,0],[0,14]].map(([fx, fy], i) => (
        <g key={i}>
          <rect x={fx} y={fy} width="7" height="7" fill="#0A0A0B" />
          <rect x={fx+1} y={fy+1} width="5" height="5" fill="#fff" />
          <rect x={fx+2} y={fy+2} width="3" height="3" fill="#0A0A0B" />
        </g>
      ))}
      {/* orange center dot */}
      <rect x="9" y="9" width="3" height="3" fill="#FC5200" />
    </svg>
  );
};

const S9_GenerateLink = () => (
  <Desk h={900} data-screen-label="09 Generate upload link">
    {/* dimmed admin behind */}
    <div style={{ position: 'absolute', inset: 0, filter: 'blur(6px) brightness(0.4)' }}>
      <div style={{ display: 'flex', height: '100%' }}>
        <AdminSidebar active="fotografos" />
        <div style={{ flex: 1, padding: 32 }}>
          <h1 style={{ fontSize: 24 }}>Fotógrafos</h1>
        </div>
      </div>
    </div>
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,11,0.7)' }} />

    {/* Modal */}
    <div style={{
      position: 'absolute', inset: 0, display: 'grid', placeItems: 'center',
    }}>
      <div style={{
        width: 860, background: '#17171A', border: '1px solid #2a2a2e', borderRadius: 16,
        display: 'grid', gridTemplateColumns: '1fr 1fr', overflow: 'hidden',
      }}>
        {/* Form */}
        <div style={{ padding: '28px 32px', borderRight: '1px solid #2a2a2e' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 22 }}>
            <h2 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 20, margin: 0, letterSpacing: '-0.02em' }}>Generar link de subida</h2>
            <I.close s={18} />
          </div>

          {[
            { l: 'Fotógrafo', v: 'Juan Pérez ▾', help: 'Asociado al evento activo.' },
            { l: 'Email (opcional)', v: 'juan@volt.gt', help: 'Le enviamos el link por correo.' },
            { l: 'Evento', v: 'Maratón Guatemala 2026 ▾', help: '' },
          ].map((f, i) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>{f.l}</label>
              <div style={{
                background: '#0e0e10', border: '1px solid #2a2a2e',
                borderRadius: 8, padding: '11px 14px', fontSize: 13,
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                <span>{f.v}</span>
              </div>
              {f.help && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{f.help}</div>}
            </div>
          ))}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Expira en</label>
              <div style={{ background: '#0e0e10', border: '1px solid #2a2a2e', borderRadius: 8, padding: '11px 14px', fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}>30 días ▾</div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Límite de fotos (opcional)</label>
              <div style={{ background: '#0e0e10', border: '1px solid #2a2a2e', borderRadius: 8, padding: '11px 14px', fontSize: 13, color: 'var(--text-3)', fontFamily: "'JetBrains Mono', monospace" }}>Sin límite</div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 28 }}>
            <Ghost size="md" full>Cancelar</Ghost>
            <CTA size="md" full>Generar link</CTA>
          </div>
        </div>

        {/* Success */}
        <div style={{ padding: '28px 32px', background: '#1f1f23', position: 'relative' }}>
          <div style={{ position: 'absolute', top: 18, right: 18, display: 'inline-grid', placeItems: 'center', width: 36, height: 36, borderRadius: 99, background: 'rgba(16,185,129,0.14)', color: '#10B981', border: '1px solid rgba(16,185,129,0.3)' }}>
            <I.check s={18}/>
          </div>

          <div className="rf-cta" style={{ fontSize: 10, color: '#10B981', letterSpacing: '0.12em', marginBottom: 8 }}>LINK GENERADO</div>
          <h3 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 20, margin: '0 0 18px', letterSpacing: '-0.02em' }}>
            Listo para compartir
          </h3>

          <label style={{ display: 'block', fontSize: 11, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>URL única</label>
          <div style={{
            background: '#0a0a0b', border: '1px solid #2a2a2e',
            borderRadius: 8, padding: '11px 14px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 18,
          }}>
            <span className="rf-num" style={{ fontSize: 13, color: '#00D4FF', letterSpacing: '0.03em' }}>runfoto.com/u/abc123x</span>
            <button style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'transparent', border: 'none', color: '#FAFAFA', fontSize: 11, cursor: 'pointer', fontWeight: 500 }}>
              <I.copy s={14}/> Copiar
            </button>
          </div>

          <div style={{ display: 'flex', justifyContent: 'center', margin: '8px 0 18px' }}>
            <QRMark size={160} />
          </div>

          <div style={{
            display: 'flex', gap: 12, padding: '12px 14px',
            background: 'rgba(245,158,11,0.08)',
            border: '1px solid rgba(245,158,11,0.25)',
            borderRadius: 8,
          }}>
            <div style={{ color: '#F59E0B', flexShrink: 0, marginTop: 1 }}>
              <I.clock s={14}/>
            </div>
            <div style={{ fontSize: 11.5, color: '#F59E0B', lineHeight: 1.45 }}>
              Compartilo solo con el fotógrafo. Expira en <span className="rf-num" style={{ fontWeight: 600 }}>30 días</span>.
            </div>
          </div>
        </div>
      </div>
    </div>
  </Desk>
);

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 10 — Approval queue
// ─────────────────────────────────────────────────────────────────────────
const S10_ApprovalQueue = () => {
  // 10 photos
  const photos = Array.from({ length: 10 }).map((_, i) => ({
    seed: i + 2,
    sel: [0, 2, 5, 7, 9].includes(i),
    initials: i % 2 === 0 ? 'JP' : 'MV',
    bib: i === 4 ? '?? Sin detectar' : `BIB ${390 + i * 8}`,
    tone: i === 4 ? 'amber' : 'cyan',
  }));
  return (
    <Desk h={1050} data-screen-label="10 Approval queue">
      <div style={{ display: 'flex', height: '100%' }}>
        <AdminSidebar active="aprobacion" />
        <div style={{ flex: 1, overflow: 'auto' }}>
          <div style={{ padding: '22px 32px', borderBottom: '1px solid #1f1f23', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h1 style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 24, margin: 0, letterSpacing: '-0.02em' }}>
                Aprobación pendiente
              </h1>
              <div className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4, letterSpacing: '0.06em' }}>23 FOTOS · 4 FOTÓGRAFOS · 2 EVENTOS</div>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <Ghost size="sm">Vista compacta</Ghost>
              <Ghost size="sm">Atajos ⌨</Ghost>
            </div>
          </div>

          {/* Filter bar */}
          <div style={{ padding: '16px 32px', display: 'flex', gap: 10, borderBottom: '1px solid #1f1f23', alignItems: 'center' }}>
            {[
              ['Evento', 'Maratón Guatemala 2026'],
              ['Fotógrafo', 'Todos'],
              ['Rango de fechas', 'Últimos 7 días'],
            ].map(([l, v], i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                background: '#17171A', border: '1px solid #2a2a2e',
                borderRadius: 8, padding: '8px 12px', fontSize: 12,
              }}>
                <span style={{ color: 'var(--text-3)' }}>{l}:</span>
                <span style={{ fontWeight: 500 }}>{v}</span>
                <span style={{ color: 'var(--text-3)' }}>▾</span>
              </div>
            ))}
            <div style={{ flex: 1 }} />
            <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)' }}>Mostrando 1–10 de 23</span>
          </div>

          {/* Bulk actions */}
          <div style={{
            margin: '16px 32px', padding: '12px 18px',
            background: 'rgba(252,82,0,0.06)', border: '1px solid rgba(252,82,0,0.25)',
            borderRadius: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <div style={{ width: 20, height: 20, borderRadius: 4, background: '#FC5200', display: 'grid', placeItems: 'center', color: '#fff' }}>
                <I.check s={12}/>
              </div>
              <span style={{ fontSize: 13, fontWeight: 500 }}>5 seleccionadas</span>
              <span style={{ color: 'var(--text-3)', fontSize: 12 }}>· <span className="rf-num">3 alta confianza</span> · <span className="rf-num">2 media</span></span>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <Ghost size="sm" tone="red">Rechazar</Ghost>
              <CTA size="sm" icon={<I.check s={14}/>}>Aprobar</CTA>
            </div>
          </div>

          {/* Grid */}
          <div style={{ padding: '8px 32px 24px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6 }}>
              {photos.map((p, i) => (
                <div key={i} style={{ position: 'relative', aspectRatio: '4/5', borderRadius: 6, overflow: 'hidden', background: '#0e0e10' }}>
                  <PhotoPH seed={p.seed} />
                  {p.sel && <div style={{ position: 'absolute', inset: 0, boxShadow: 'inset 0 0 0 3px #FC5200', pointerEvents: 'none' }} />}
                  {/* checkbox */}
                  <div style={{
                    position: 'absolute', top: 8, left: 8,
                    width: 20, height: 20, borderRadius: 4,
                    background: p.sel ? '#FC5200' : 'rgba(10,10,11,0.6)',
                    border: p.sel ? 'none' : '1px solid rgba(255,255,255,0.5)',
                    display: 'grid', placeItems: 'center', color: '#fff', backdropFilter: 'blur(4px)',
                  }}>{p.sel && <I.check s={12}/>}</div>
                  {/* photographer avatar */}
                  <div style={{
                    position: 'absolute', top: 8, right: 8,
                    width: 24, height: 24, borderRadius: 99,
                    background: p.initials === 'JP' ? 'linear-gradient(135deg, #2A6FDB, #1a4a96)' : 'linear-gradient(135deg, #8b5cf6, #5a3aa5)',
                    color: '#fff',
                    fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 9,
                    display: 'grid', placeItems: 'center', letterSpacing: '0.05em',
                    border: '1px solid rgba(10,10,11,0.6)',
                  }}>{p.initials}</div>
                  {/* bib bottom-left */}
                  <div style={{ position: 'absolute', bottom: 8, left: 8 }}>
                    <Bib n={p.bib} tone={p.tone} />
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 22 }}>
              <Ghost size="md">Cargar 13 fotos más</Ghost>
            </div>
          </div>
        </div>
      </div>
    </Desk>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// SCREEN 11 — Approval detail drawer
// ─────────────────────────────────────────────────────────────────────────
const S11_ApprovalDetail = () => {
  const exif = [
    ['Cámara', 'Sony A9 II'],
    ['Lente', '70-200mm f/2.8'],
    ['Apertura', 'f/2.8'],
    ['Velocidad', '1/2000s'],
    ['ISO', '400'],
    ['Tamaño', '8.4 MB'],
  ];
  return (
    <Desk h={950} data-screen-label="11 Approval detail">
      <div style={{ display: 'flex', height: '100%' }}>
        <AdminSidebar active="aprobacion" />
        <div style={{ flex: 1, position: 'relative', background: '#050506' }}>
          {/* Dimmed photo on left */}
          <div style={{
            position: 'absolute', left: 0, right: 480, top: 0, bottom: 0,
            display: 'grid', placeItems: 'center', padding: 48,
          }}>
            <div style={{ position: 'relative', width: '100%', maxWidth: 560, aspectRatio: '4/5', borderRadius: 6, overflow: 'hidden' }}>
              <PhotoPH seed={4} label="" />
              <Watermark text="RUNFOTO • PENDING REVIEW" rotate={-30} opacity={0.18} size={14} />
            </div>
            {/* Floating nav hints */}
            <div style={{ position: 'absolute', bottom: 24, left: 0, right: 480, display: 'flex', justifyContent: 'center', gap: 12 }}>
              <button style={{ width: 36, height: 36, borderRadius: 99, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.left s={16}/></button>
              <div style={{ display: 'flex', alignItems: 'center', padding: '0 16px', background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', borderRadius: 8 }}>
                <span className="rf-num" style={{ fontSize: 11, color: 'var(--text-2)' }}>3 / 23</span>
              </div>
              <button style={{ width: 36, height: 36, borderRadius: 99, background: 'rgba(255,255,255,0.06)', border: '1px solid #2a2a2e', color: '#FAFAFA', display: 'grid', placeItems: 'center', cursor: 'pointer' }}><I.right s={16}/></button>
            </div>
          </div>

          {/* Drawer right */}
          <div style={{
            position: 'absolute', right: 0, top: 0, bottom: 0, width: 480,
            background: '#0e0e10', borderLeft: '1px solid #1f1f23',
            display: 'flex', flexDirection: 'column',
          }}>
            <div style={{ padding: '22px 26px 18px', borderBottom: '1px solid #1f1f23' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <Pill tone="amber" dot="pulse" size="md">PENDIENTE DE REVISIÓN</Pill>
                <I.close s={18} />
              </div>
              <h2 className="rf-num" style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 14, margin: 0, color: '#FAFAFA', letterSpacing: 0 }}>
                IMG_0247_volt.jpg
              </h2>
              <div className="rf-num" style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 6, letterSpacing: '0.06em' }}>
                CAPTURADA · 15 NOV 2026 · 09:24:37 AM
              </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 26px' }}>
              {/* EXIF */}
              <div className="rf-cta" style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.12em', marginBottom: 10 }}>DATOS TÉCNICOS</div>
              <div style={{ background: '#17171A', border: '1px solid #1f1f23', borderRadius: 10, overflow: 'hidden', marginBottom: 22 }}>
                {exif.map(([k, v], i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between',
                    padding: '10px 14px', borderBottom: i < exif.length - 1 ? '1px solid #1f1f23' : 'none',
                  }}>
                    <span style={{ fontSize: 12, color: 'var(--text-2)' }}>{k}</span>
                    <span className="rf-num" style={{ fontSize: 12, fontWeight: 500, color: '#FAFAFA' }}>{v}</span>
                  </div>
                ))}
              </div>

              {/* Dorsales detectados */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <div className="rf-cta" style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.12em' }}>DORSALES DETECTADOS</div>
                <Pill tone="green" size="sm">Alta confianza</Pill>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {['402', '518'].map((n) => (
                  <span key={n} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    background: 'rgba(0,212,255,0.10)', border: '1px solid rgba(0,212,255,0.25)',
                    borderRadius: 6, padding: '7px 10px',
                    color: '#00D4FF', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 13,
                  }}>
                    #{n}
                    <span style={{ color: 'rgba(0,212,255,0.6)', cursor: 'pointer' }}><I.close s={12}/></span>
                  </span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <input placeholder="Agregar dorsal..." style={{
                  flex: 1, background: '#0a0a0b', border: '1px solid #2a2a2e',
                  borderRadius: 8, padding: '9px 12px', fontSize: 12, color: '#FAFAFA',
                  outline: 'none', fontFamily: "'JetBrains Mono', monospace",
                }} />
                <Ghost size="sm">Agregar</Ghost>
              </div>

              {/* Photographer card */}
              <div className="rf-cta" style={{ fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.12em', margin: '24px 0 10px' }}>FOTÓGRAFO</div>
              <div style={{
                background: '#17171A', border: '1px solid #1f1f23', borderRadius: 10,
                padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12,
              }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 99,
                  background: 'linear-gradient(135deg, #2A6FDB, #1a4a96)',
                  color: '#fff', fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 13,
                  display: 'grid', placeItems: 'center',
                }}>JP</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Juan Pérez</div>
                  <div className="rf-num" style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2, letterSpacing: '0.06em' }}>
                    247 SUBIDAS · 96% APROBADAS
                  </div>
                </div>
                <I.right s={14}/>
              </div>
            </div>

            {/* Footer actions */}
            <div style={{ padding: '16px 26px 18px', borderTop: '1px solid #1f1f23' }}>
              <div style={{ display: 'flex', gap: 10 }}>
                <Ghost size="md" tone="red" full>Rechazar</Ghost>
                <CTA size="md" full icon={<I.check s={14}/>}>Aprobar</CTA>
              </div>
              <div className="rf-num" style={{ fontSize: 10, color: 'var(--text-3)', textAlign: 'center', marginTop: 12, letterSpacing: '0.08em' }}>
                A APROBAR · R RECHAZAR · → SIGUIENTE
              </div>
            </div>
          </div>
        </div>
      </div>
    </Desk>
  );
};

Object.assign(window, { S8_AdminDashboard, S9_GenerateLink, S10_ApprovalQueue, S11_ApprovalDetail });
