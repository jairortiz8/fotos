/* RunFoto — Print layout (one artboard per page) */

const PrintPage = ({ label, width, height, children }) => {
  // Each page renders at "print-page" CSS dimensions; the artboard is scaled
  // to fit via CSS scale on the wrapper.
  return (
    <div className="print-page" data-screen-label={label}>
      <div className="print-label">
        <span className="rf-num" style={{ fontSize: 10, color: '#6B6B70', letterSpacing: '0.08em' }}>
          RUNFOTO · {label.toUpperCase()}
        </span>
        <span className="rf-num" style={{ fontSize: 10, color: '#6B6B70', letterSpacing: '0.08em' }}>
          {width} × {height}
        </span>
      </div>
      <div
        className="print-frame"
        style={{
          width: width,
          height: height,
          // The actual scaling is done by CSS via the parent container's
          // available width / artboard width. We set --w / --h for math.
        }}
      >
        {children}
      </div>
    </div>
  );
};

const PrintApp = () => (
  <div className="print-root">
    {/* Section title page */}
    <div className="print-page print-cover">
      <div>
        <div className="rf-cta" style={{ fontSize: 12, color: '#6B6B70', letterSpacing: '0.16em', marginBottom: 18 }}>SISTEMA DE DISEÑO</div>
        <Wordmark size={88} />
        <div style={{ marginTop: 28, fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 28, color: '#FAFAFA', letterSpacing: '-0.02em', maxWidth: 700 }}>
          Plataforma gratuita de fotos de carrera.
        </div>
        <div style={{ marginTop: 14, fontSize: 15, color: '#A1A1A6', maxWidth: 640, lineHeight: 1.55 }}>
          12 pantallas · público, fotógrafo y admin. Búsqueda por dorsal y por selfie.
          Descarga libre, sin cuentas para corredores ni fotógrafos.
        </div>
        <div className="rf-num" style={{ marginTop: 48, fontSize: 11, color: '#6B6B70', letterSpacing: '0.08em' }}>
          GUATEMALA · 14 NOV 2026
        </div>
      </div>
    </div>

    <PrintPage label="01 · Landing (mobile)" width={390} height={844}><S1_Mobile /></PrintPage>
    <PrintPage label="01 · Landing (desktop)" width={1440} height={900}><S1_Desktop /></PrintPage>
    <PrintPage label="02 · Galería · Por dorsal ★" width={1440} height={1200}><S2_GalleryBib /></PrintPage>
    <PrintPage label="03 · Galería · Por selfie" width={1440} height={1100}><S3_GallerySelfie /></PrintPage>
    <PrintPage label="04 · Empty state" width={1440} height={900}><S4_Empty /></PrintPage>
    <PrintPage label="05 · Lightbox" width={1440} height={900}><S5_Lightbox /></PrintPage>
    <PrintPage label="06 · Descarga (mobile)" width={390} height={844}><S6_DownloadSheet /></PrintPage>
    <PrintPage label="07 · Portal del fotógrafo" width={1440} height={1200}><S7_PhotographerPortal /></PrintPage>
    <PrintPage label="08 · Admin · Dashboard" width={1440} height={950}><S8_AdminDashboard /></PrintPage>
    <PrintPage label="09 · Generar link" width={1440} height={900}><S9_GenerateLink /></PrintPage>
    <PrintPage label="10 · Cola de aprobación" width={1440} height={1050}><S10_ApprovalQueue /></PrintPage>
    <PrintPage label="11 · Detalle de aprobación" width={1440} height={950}><S11_ApprovalDetail /></PrintPage>
    <PrintPage label="12 · Galería · Light mode" width={1440} height={1200}><S2_GalleryBib light /></PrintPage>
  </div>
);

ReactDOM.createRoot(document.getElementById('root')).render(<PrintApp />);

// Mark loaded for auto-print trigger
window.__printAppReady = true;
