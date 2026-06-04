# Contribuir a RunFoto

Guía corta para trabajar en el código de RunFoto sin pisar nada. Esto NO es un
proyecto de equipo grande: es el proyecto de Jair, así que la idea es mantenerlo
prolijo y predecible.

## Setup

El setup del entorno local (Postgres, Redis, dependencias, variables de entorno)
está en el [README](../README.md). No lo repetimos acá: seguí esos pasos primero.

## Antes de commitear

Corré todo esto y que quede **todo en verde** antes de hacer un commit:

```bash
ruff check .      # linter (errores de estilo y bugs comunes)
ruff format .     # formato automático con ruff
black .           # formato de código
mypy .            # chequeo de tipos
pytest            # tests
```

Si algo sale en rojo, se arregla antes de commitear. Los pre-commit hooks corren
una parte de esto automáticamente, pero conviene correrlo a mano también.

## Estilo de commits

Usamos **Conventional Commits**: el mensaje empieza con un prefijo que dice qué
tipo de cambio es.

- `feat:` — una funcionalidad nueva
- `fix:` — arreglo de un bug
- `chore:` — tareas de mantenimiento (deps, config, etc.)
- `docs:` — sólo documentación
- `refactor:`, `test:`, `ci:`, etc. — según corresponda

Ejemplo:

```
feat(search): cachear búsquedas por dorsal 5 min en Redis
```

El prefijo entre paréntesis (`search`) es opcional e indica el área del proyecto.

## Branches y fases

El proyecto se construye **en fases** (están listadas en `CLAUDE.md`). Cada fase
es un bloque de trabajo cerrado. Una fase se cierra así:

1. Todos los tests + el linter en verde.
2. Commit con mensaje descriptivo.
3. Push.
4. Deploy a Railway si aplica.
5. Resumen de qué se hizo, y **esperar el OK de Jair** antes de empezar la
   siguiente fase.

## Tests

- Framework: **pytest** + **factory-boy** para las fixtures.
- **Cobertura mínima: 80%**, y **85% en código de privacidad y core** (es la
  parte sensible: borrado de datos, retención de embeddings, auth).
- **Cada feature viene con sus tests.** No se mergea código nuevo sin tests que lo
  cubran.

## Qué NO hacer

- ❌ **No commitear secrets ni `.env`.** Las credenciales van por variables de
  entorno (Railway secrets en prod), nunca al repo.
- ❌ **No borrar tests existentes** (salvo que Jair lo apruebe explícitamente).
- ❌ **No hardcodear "RunFoto"** en templates ni código. Usar `{{ site_name }}`
  (o la variable de entorno `SITE_NAME`). El nombre puede cambiar.
- ❌ **No cambiar el stack sin aprobación.** Django, HTMX, R2, Railway, Postgres,
  etc. están decididos. Cambiar algo de eso se conversa primero (ver `CLAUDE.md`
  §8).
