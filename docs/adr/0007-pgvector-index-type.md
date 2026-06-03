# ADR 0007 — Tipo de índice pgvector: HNSW

- **Fecha**: 2026-06-02
- **Estado**: Aceptado
- **Decisores**: Jair

## Contexto

La búsqueda por selfie hace una query de vecinos más cercanos (k-NN) sobre la
tabla `photos_faceembedding` usando distancia coseno. Sin un índice apropiado,
Postgres hace un *sequential scan* y calcula la distancia contra TODOS los
embeddings — O(n) por query, lento cuando crece la tabla.

pgvector ofrece dos tipos de índice ANN (Approximate Nearest Neighbor):

| | IVFFlat | HNSW |
| --- | --- | --- |
| Build time | Rápido | Más lento |
| Query speed | Bueno | Mejor |
| Recall | Bueno (depende de `lists`/`probes`) | Mejor |
| Requiere datos para construir | Sí (k-means) | No |
| Memoria | Menor | Mayor |
| Updates incrementales | Reconstruir para óptimo | Soporta bien inserts |

## Decisión

Usamos **HNSW** con `vector_cosine_ops`, `m = 16`, `ef_construction = 64`.

Definido en `apps/photos/models.py::FaceEmbedding.Meta.indexes` (creado por
Django migrations, no SQL manual):

```python
HnswIndex(
    name="face_embedding_hnsw_cos",
    fields=["embedding"],
    m=16,
    ef_construction=64,
    opclasses=["vector_cosine_ops"],
)
```

## Razones

1. **Mejor recall y query speed** que IVFFlat para nuestros volúmenes
   proyectados (~180k embeddings año 1: 4.000 fotos × ~3 caras × 15 eventos).
   HNSW brilla justamente en el rango "pequeño a mediano".
2. **No requiere datos para construirse**. IVFFlat necesita correr k-means
   sobre vectores existentes para definir las "listas"; si creás el índice con
   la tabla vacía, queda mal calibrado. HNSW se construye incrementalmente —
   importante porque los embeddings llegan de a poco (foto por foto).
3. **Maneja bien los inserts incrementales** sin degradar — nuestro caso, ya
   que cada upload agrega embeddings.
4. El costo (build más lento, más memoria) es irrelevante a esta escala.

## Parámetros

- `m = 16`: conexiones por nodo en el grafo. 16 es el default recomendado;
  balance memoria/recall.
- `ef_construction = 64`: tamaño de la lista dinámica al construir. Más alto =
  mejor índice pero build más lento. 64 es conservador-bueno.
- En query, `ef_search` (default 40) controla recall vs velocidad. Si hace
  falta más recall, se sube con `SET hnsw.ef_search = N` antes de la query.

## Verificación

`tests/ml/test_pgvector_index.py::test_hnsw_index_exists` chequea que el índice
existe en `pg_indexes` con `vector_cosine_ops`. Un `EXPLAIN ANALYZE` de la query
de búsqueda confirma que usa `Index Scan using face_embedding_hnsw_cos`.

## Cuándo reevaluar

- Si superamos ~1M de embeddings: evaluar `m=32` para mejor recall, o sharding.
- Si la memoria del Postgres de Railway se vuelve un problema: considerar
  IVFFlat (menos memoria) aceptando recall algo menor.

## Consecuencias

### Positivas
- Queries de búsqueda por selfie rápidas y con buen recall desde el día 1.
- Sin paso de calibración (k-means) que complicaría el deploy.

### Negativas / riesgos
- HNSW usa más RAM que IVFFlat. A 180k vectores de 512 dims (~370 MB de datos
  crudos) el índice cabe holgado en el Postgres de Railway. Reevaluar a escala.
- Build del índice más lento, pero es un costo único por migración, no por query.
