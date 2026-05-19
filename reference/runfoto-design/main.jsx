/* RunFoto — Design canvas composition */

const App = () => (
  <DesignCanvas title="RunFoto" subtitle="Plataforma gratuita de fotos de carrera · 12 pantallas">

    <DCSection id="public" title="Público — Corredor" subtitle="Búsqueda y descarga de fotos. Sin cuenta.">
      <DCArtboard id="s1-mobile" label="01 · Landing (mobile)" width={390} height={844}>
        <S1_Mobile />
      </DCArtboard>
      <DCArtboard id="s1-desktop" label="01 · Landing (desktop)" width={1440} height={900}>
        <S1_Desktop />
      </DCArtboard>
      <DCArtboard id="s2" label="02 · Galería · Búsqueda por dorsal ★" width={1440} height={1200}>
        <S2_GalleryBib />
      </DCArtboard>
      <DCArtboard id="s3" label="03 · Galería · Búsqueda por selfie" width={1440} height={1100}>
        <S3_GallerySelfie />
      </DCArtboard>
      <DCArtboard id="s4" label="04 · Empty state" width={1440} height={900}>
        <S4_Empty />
      </DCArtboard>
      <DCArtboard id="s5" label="05 · Lightbox" width={1440} height={900}>
        <S5_Lightbox />
      </DCArtboard>
      <DCArtboard id="s6" label="06 · Descarga múltiple (mobile)" width={390} height={844}>
        <S6_DownloadSheet />
      </DCArtboard>
      <DCArtboard id="s12" label="12 · Galería · Light mode" width={1440} height={1200}>
        <S2_GalleryBib light />
      </DCArtboard>
    </DCSection>

    <DCSection id="photographer" title="Fotógrafo — Portal de subida" subtitle="Acceso por token único. Una sola página, sin sidebar, sin cuenta.">
      <DCArtboard id="s7" label="07 · Portal del fotógrafo" width={1440} height={1200}>
        <S7_PhotographerPortal />
      </DCArtboard>
    </DCSection>

    <DCSection id="admin" title="Admin — Super admin" subtitle="Una sola cuenta. Aprobación, eventos, fotógrafos, estadísticas.">
      <DCArtboard id="s8" label="08 · Dashboard" width={1440} height={950}>
        <S8_AdminDashboard />
      </DCArtboard>
      <DCArtboard id="s9" label="09 · Generar link de subida" width={1440} height={900}>
        <S9_GenerateLink />
      </DCArtboard>
      <DCArtboard id="s10" label="10 · Cola de aprobación" width={1440} height={1050}>
        <S10_ApprovalQueue />
      </DCArtboard>
      <DCArtboard id="s11" label="11 · Detalle de aprobación" width={1440} height={950}>
        <S11_ApprovalDetail />
      </DCArtboard>
    </DCSection>

  </DesignCanvas>
);

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
