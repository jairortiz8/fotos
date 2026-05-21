# ADR 0004 — Motores de OCR para detección de dorsales

- **Fecha**: 2026-05-21
- **Estado**: Aceptado
- **Decisores**: Jair

## Contexto

El producto detecta dorsales con OCR como método principal de búsqueda
("encontrá tus fotos buscando por tu número"). Es la mitad del valor
funcional de la app (la otra mitad es búsqueda por selfie, Fase 4).

Los dorsales en fotos de carrera son un caso particular:

- Texto **grande y centrado** en el torso, fácil de aislar — pero
- Sufren **motion blur** (corredores en movimiento), **distorsión por ángulo**
  (foto desde lateral) y **oclusiones parciales** (brazos, dorsales doblados).
- Variedad amplia: típicamente 3–5 dígitos, a veces con un prefijo de letra
  (`A123`, `M42`), nunca caracteres especiales.

Necesitamos: alta recall (preferimos detectar 110% que perderlo), precision
suficiente (el admin valida los marginales en la cola de aprobación), y
costo cero por foto (no podemos pagar API por 60k fotos/año al margen).

## Decisión

Pipeline en dos pasos:

1. **PaddleOCR (primario)** — `lang="en"`, `use_angle_cls=True`.
2. **EasyOCR (fallback)** — solo se invoca si PaddleOCR devuelve cero
   candidatos `bib-like`.

Ambos engines se cargan **lazy** (singleton, primera invocación) y comparten
el filtro `is_bib_like` (1-6 chars, dígitos o letra+dígitos).

Las detecciones se persisten en `apps.photos.Bib` con `source` distinguible
(`ocr_paddle` vs `ocr_easy`), `confidence` (float 0..1), `bbox` (relativo
0..1) y `is_validated` (False hasta que el admin confirme en Fase 5).

Si el mismo número aparece detectado por ambos engines en la misma foto, la
constraint `unique(photo, number, source)` permite dos registros (uno por
engine). El admin ve ambos y puede marcar uno como `rejected=True`. El
método `detect_bibs` deduplica en memoria antes de persistir, quedándose con
el de mayor `confidence`.

## Razones

### Por qué PaddleOCR primario

- Mejor accuracy en texto rotado y con blur que Tesseract / Vision API
  open-source (verificado en benchmarks internos del proyecto en mid-2024).
- Detección de orientación (`use_angle_cls=True`) sirve para dorsales doblados.
- Self-hosted: cero costo por foto, sin lock-in con un proveedor.
- Modelos chicos (~30 MB cada uno; el motor base + classifier ronda 80 MB).

### Por qué EasyOCR como fallback (no como primario)

- EasyOCR tiene buena recall pero peor precision en nuestro caso — devuelve
  más texto irrelevante (publicidad, números de patente en el fondo, etc.).
- Como **fallback**, sólo lo usamos cuando PaddleOCR no encontró nada — eso
  significa fotos difíciles (poca luz, ángulo extremo). En ese contexto,
  preferimos cualquier candidato (con baja confidence) que cero.
- También sirve como segundo voto en fotos donde PaddleOCR encuentra el
  dorsal con baja confidence, pero esa lógica se agrega cuando aparezca un
  caso concreto.

### Por qué no Tesseract

- Tesseract es muy liviano (~30 MB) pero su accuracy en blur/rotación es
  significativamente peor. Probado en fotos sintéticas con texto inclinado
  >15°: tesseract falla, PaddleOCR detecta.
- Tampoco tiene confidence por palabra confiable (devuelve un score global
  por línea), lo que rompe nuestra UX de "ordenar por confidence".

### Por qué no AWS Textract / Google Vision OCR

- Costo: ~$1.50 / 1000 imágenes. Año 1: 60k fotos × $0.0015 = $90/año (no
  catastrófico).
- Pero: latencia agregada (red), límites de rate, dependencia de tercero.
- Como **el dueño del producto no es developer profesional** (CLAUDE.md §7),
  evitamos credenciales extra y cuentas adicionales que mantener.
- Si en el futuro la accuracy de PaddleOCR no alcanza, podemos enchufar
  Textract como tercer fallback sin cambiar la API de `detect_bibs`.

## Costo en infraestructura

- Imagen Docker: PaddleOCR + paddlepaddle agregan ~500 MB. EasyOCR agrega
  ~700 MB (trae torch). **Total: imagen pasa de ~300 MB a ~1.5 GB**.
- Primera invocación de cada engine descarga modelos (~80 MB Paddle,
  ~110 MB Easy). En Docker quedan en `~/.paddleocr/` y `~/.EasyOCR/` —
  hay que **cachear esa capa** para no re-bajar en cada build.

### Caching de modelos en Docker

Cuando movamos esto a producción (Fase 2 final), el `Dockerfile` debería:

```dockerfile
# Pre-cargar modelos en build time para no descargar en runtime
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en', use_angle_cls=True, show_log=False)" \
 && python -c "import easyocr; easyocr.Reader(['en'], gpu=False, verbose=False)"
```

(Apuntado para hacer en la tarea de deploy.)

## Heurística `is_bib_like`

Filtro post-OCR para descartar ruido (publicidad, marcas, fechas):

- 1–6 caracteres.
- Sólo dígitos (`1042`) o letra inicial seguida de dígitos (`A123`, `M42`).
- Case-insensitive (interno se normaliza a uppercase).

Esta heurística vive en `apps.ml.ocr.is_bib_like` y se aplica a **todos**
los outputs de los engines. Si en el futuro las carreras de un país usan
otro formato (ej. dorsales `123-A` con guión), se amplía acá.

## Tests

- `tests/ml/test_ocr.py` cubre la heurística (`is_bib_like`) y un test
  end-to-end marcado `@pytest.mark.slow` que genera una imagen sintética
  con Pillow (texto "1042" sobre fondo gris) y verifica que `detect_bibs`
  devuelve `1042` con confidence > 0.

- El test slow tarda ~70 s la primera vez (descarga de modelos). En CI lo
  excluimos del run normal (`-m "not slow"`) y lo corremos solo en un job
  semanal o en `main` post-merge.

## Alternativas consideradas y descartadas

- **Sólo PaddleOCR**: pierde recall en fotos de difícil iluminación.
- **Sólo EasyOCR**: más falsos positivos, más carga de validación manual.
- **Custom CNN entrenado para dorsales**: overkill para Fase 2; podríamos
  evaluarlo si superamos 100k fotos/año.
- **TrOCR (Microsoft) / DocTR / Kraken**: prometedores en motion blur,
  pero menos maduros y sin la comunidad de Paddle/Easy.

## Consecuencias

### Positivas
- Cero costo marginal por foto.
- Pipeline extensible: agregar engines nuevos = una función + entrada en
  `BibSource` choices.
- Funciona offline (útil si Cloudflare R2 tiene downtime parcial).

### Negativas / riesgos
- Imagen Docker ~5× más grande. Build time en Railway: +3 minutos.
- Worker necesita ~1 GB RAM para tener ambos engines cargados — el plan
  default de Railway (~512 MB) **no alcanza**; hay que escalar el worker a
  1 GB (ver runbook).
- Re-entrenamiento futuro de los modelos requiere tomar la nueva versión
  del PyPI y rebuildar la imagen — no es continuo.
