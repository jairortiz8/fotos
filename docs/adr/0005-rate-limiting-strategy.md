# ADR 0005 — Estrategia de rate limiting

- **Fecha**: 2026-06-02
- **Estado**: Aceptado
- **Decisores**: Jair

## Contexto

RunFoto es 100% público, sin cuentas. Cualquiera puede buscar dorsales y
descargar ZIPs. Eso lo expone a dos clases de abuso:

1. **Scraping masivo**: un bot que enumera dorsales (`0001`, `0002`, …) para
   bajarse todas las fotos de un evento y republicarlas / venderlas.
2. **Abuso de recursos**: los ZIPs son caros de generar (bajar N originales de
   R2, comprimirlos, re-subir). Un atacante podría disparar miles de ZIPs y
   saturar los workers + el egress de R2.

Como no hay login, el único identificador es la IP (imperfecta: NAT, móviles
rotando IP, etc.), así que combinamos varias capas en lugar de confiar en una.

## Decisión

Tres capas de rate limiting, todas con `django-ratelimit` sobre Redis:

| Capa | Límite | Clave | Dónde |
| ---- | ------ | ----- | ----- |
| **General de búsqueda** | 60 / hora | IP | `check_general_search_rate_limit` |
| **Por dorsal específico** | 10 / día | (IP, evento, dorsal) | `check_bib_specific_rate_limit` |
| **Descarga ZIP** | 5 / hora | IP | `check_zip_rate_limit` |

Implementadas en `apps/core/utils.py` con la API programática
`django_ratelimit.core.is_ratelimited`, no con decoradores — porque la galería
sin búsqueda NO debe consumir cupo, sólo las búsquedas reales.

### Por qué dos capas para búsqueda

- **60/h por IP** frena el scraping enumerativo: un bot que pruebe 1000
  dorsales se corta a los 60.
- **10/día por (IP, dorsal)** es anti-retry abusivo: si alguien busca el mismo
  dorsal 10 veces en un día ya tiene sus fotos; un 11º intento es sospechoso
  (o un bot reintentando). Esta capa es más fina y ataca un patrón distinto.

Las dos juntas cubren tanto "muchos dorsales distintos" como "el mismo dorsal
muchas veces".

### Cache de búsqueda (5 min)

Ortogonal al rate limit pero relacionado: cada búsqueda exitosa se cachea 5
minutos en Redis (`search:bib:<event>:<dorsal>`). Esto:
- Reduce carga en Postgres ante búsquedas repetidas (un corredor que recarga).
- **Guardamos IDs, no objetos** — para no cachear signed URLs que expiran.

## Respuestas

Cuando se excede un límite:
- Búsqueda → `429` + template `public/rate_limited.html` (mensaje amigable).
- ZIP → `429` + JSON `{"error": "rate_limited"}`.

No exponemos cuánto falta para resetear (no le damos información al atacante).

## Privacidad

- **No guardamos la IP cruda** en ningún lado. El rate limiting vive en Redis
  con TTL; cuando expira, desaparece.
- Para logging persistente (ej. `ZipDownload.requester_ip_hash`) guardamos
  `sha256(IP)`, no la IP. Cumple CLAUDE.md §3 (no loggear PII).
- `record_search` NO se implementó como modelo: no queremos una tabla con
  "qué dorsal buscó cada IP" (sería data sensible). Solo incrementamos el
  contador denormalizado `Event.search_count`.

## Alternativas consideradas

- **Sólo IP, una capa**: insuficiente contra el mismo-dorsal-repetido.
- **Cookies / fingerprinting**: más invasivo, choca con la promesa de
  privacidad, y evadible.
- **CAPTCHAs**: CLAUDE.md prohíbe que el sistema complete CAPTCHAs, y poner uno
  al corredor arruina la UX ("es gratis y sin fricción" es el diferencial).
- **Cloudflare WAF / rate limiting en el edge**: complementario, lo podemos
  sumar en el futuro (las fotos ya van por R2/Cloudflare). Hoy preferimos
  tener la lógica en la app para no depender de config externa.

## Consecuencias

### Positivas
- Tres patrones de abuso distintos cubiertos con poca complejidad.
- Cero PII almacenada.
- Configurable: los rates están en strings (`"60/h"`) fáciles de tunear.

### Negativas / riesgos
- IP-based: usuarios detrás de NAT grande (oficina, universidad) comparten
  cupo. Mitigación: los límites son generosos (60/h es mucho para un humano).
- Móviles rotando IP evaden parcialmente. Aceptable: el costo de scrapear con
  IP rotation es alto y el contenido es de bajo valor de reventa.
- Redis es punto único: si se cae, `is_ratelimited` falla. django-ratelimit
  por default **falla abierto** (permite) si el cache no responde — preferible
  a bloquear a todos los usuarios legítimos.
