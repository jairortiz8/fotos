# ADR 0006 — Umbral de similitud facial + detección de menores

- **Fecha**: 2026-06-02
- **Estado**: Aceptado (umbral provisional, a calibrar con fotos reales)
- **Decisores**: Jair

## Contexto

La búsqueda por selfie compara el embedding del selfie del usuario contra los
embeddings de las caras de las fotos del evento (InsightFace `buffalo_l`,
vectores de 512 dims, normalizados L2). La métrica es **similitud coseno**
(equivalente a producto interno tras normalizar).

Hay que elegir:
1. El **umbral de similitud** para considerar que dos caras son la misma persona.
2. El **umbral de edad** para blurear menores.

## Decisión

### Umbral de búsqueda por selfie: 0.55 (provisional)

- `SIMILARITY_THRESHOLD = 0.55` en `apps/search/views.py`.
- Una foto aparece en resultados si `max(cosine_similarity) >= 0.55` entre el
  selfie y cualquiera de sus caras.
- Los resultados se agrupan en la UI por confianza: **alta** (≥80%), **media**
  (60-79%), **baja** (55-59%).

### Umbral de borrado de datos: 0.62 (más estricto)

- `DELETION_THRESHOLD = 0.62` en `apps/privacy/views.py`.
- Más alto que la búsqueda porque borrar es irreversible: preferimos NO borrar
  una foto dudosa que borrar la de otra persona por un falso positivo.

### Detección de menores (decisión de Jair)

Dos umbrales de edad, porque el estimador de InsightFace es impreciso (±5-10 años):

- `MINOR_BLUR_AGE = 16`: caras estimadas **< 16** → `is_minor=True` → **blur
  automático** del preview/thumbnail. El original queda intacto.
- `MINOR_REVIEW_AGE = 22`: caras estimadas **< 22** → la foto se marca
  `needs_minor_review=True` para que el **admin revise** manualmente en la cola
  de aprobación (Fase 5) si las caras de 16-21 dudosas requieren blur.

Racional: el blur automático agresivo (ej. <20) molestaría a muchos adultos
jóvenes. El blur automático conservador (<16) captura los casos claros; las
zonas grises (16-21) las decide un humano. Así combinamos protección
automática + control humano, sin sobre-blurear.

## Por qué 0.55 es provisional

InsightFace `buffalo_l` con embeddings normalizados produce típicamente:
- Misma persona: cosine similarity ~0.5-0.8 (depende de pose, luz, edad de la foto).
- Personas distintas: ~0.0-0.3.

0.55 es un punto de partida razonable de la literatura, **pero hay que
calibrarlo con fotos reales del contexto** (corredores en movimiento, sudados,
con gorra/lentes, fotografiados de lado). Para eso está el comando:

```bash
python manage.py tune_threshold \
    --selfie selfie.jpg \
    --positives carpeta_misma_persona/ \
    --negatives carpeta_otras_personas/
```

Reporta la distribución de similitudes de positivos vs negativos y sugiere un
umbral que los separe. **Cuando Jair tenga un evento real, hay que correrlo y
actualizar este ADR con el valor final.**

## Trade-offs del umbral

- **Más bajo** (ej. 0.45): más recall (encontrás más fotos tuyas) pero más
  falsos positivos (aparecen caras que no son vos). Molesto pero no grave en
  búsqueda; peligroso en borrado.
- **Más alto** (ej. 0.65): menos falsos positivos pero podés perder fotos
  donde salís de costado o con mala luz.

Para un producto de "encontrá tus fotos", preferimos pecar de recall en la
búsqueda (que el usuario filtre visualmente entre los resultados) y de
precision en el borrado.

## Rollback

El umbral es una constante en código. Si tras un cambio hay quejas:
1. Revertí `SIMILARITY_THRESHOLD` / `DELETION_THRESHOLD` al valor anterior.
2. Redeploy. No requiere migración ni reprocesar embeddings.
Documentado en `docs/runbook.md`.

## Consecuencias

- El umbral inicial puede dar falsos positivos/negativos hasta calibrar.
  Mitigación: la UI agrupa por confianza, así el usuario entiende qué tan
  segura es cada coincidencia.
- El blur de menores depende de un estimador impreciso. Mitigación: el doble
  umbral (auto <16 + review <22) + el admin como red de seguridad.
