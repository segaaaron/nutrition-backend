# Peticiones de iOS a Backend — verificadas una a una contra su código

**Fecha:** 2026-08-25 (revisión final) · **De:** iOS (Nova Nutrition AI) · **Para:** Backend
**Revisado contra:** `8a1d6b0`, que es lo que corre en PROD. No contra sus notas ni contra las nuestras.

---

## Antes de nada: nos disculpamos por el ruido de las listas anteriores

Los informes previos daban por abiertos **21 puntos que ustedes ya habían resuelto**. Once los cerró
`8a1d6b0` esta misma tarde; los otros diez llevaban semanas o meses hechos y nosotros seguíamos
pidiéndolos porque nunca los verificamos contra su código.

Esta versión está construida al revés: **cada punto se ha ido a comprobar al repositorio antes de
escribirlo**, y lleva la línea exacta donde se comprobó. Lo que ya está hecho aparece cerrado, con la
evidencia, para que no vuelvan a leer una petición de algo que entregaron.

## Qué necesitamos, en orden

1. **Credenciales de una cuenta de prueba** — y una con `role='admin'`. Es lo único que nos bloquea
   de verdad: tenemos seis entregas terminadas que no podemos verificar porque no podemos abrir la
   app con una sesión.
2. **C12** (los vasos de agua no se guardan en ningún sitio) y **C18** (`persist_calibration`). Son
   las dos que hoy limitan una pantalla en producción.
3. **C6-b, C14, C20** cuando puedan: los tres nos hacen enseñar algo peor de lo que podríamos.
4. El resto es higiene suya y no corre prisa.

---

# Parte 1 — Cerrado. No hace falta que hagan nada

## 1.a Lo que entregó `8a1d6b0` y ya consumimos (11)

Todo esto está cableado y en producción **de nuestro lado** desde el mismo día.

| # | Qué pedíamos | Dónde lo comprobamos |
|---|---|---|
| **C2** | `/images/**` respondía 403 a cualquier cliente sin UA de Nova | `anti_sniff.py:89` — y `curl` a PROD ya devuelve 404, no 403 |
| **C3** | Sin `Cache-Control`/`ETag` en las imágenes | `main.py` — `StaticImageCacheMiddleware`, `immutable` + `ETag` |
| **C4** | El cliente no sabía el rol de la cuenta | `profile/presentation/schemas.py:358` — `role: str = "user"` |
| **C11** | Las alternativas de swap eran UUIDs crudos | `plan/presentation/schemas.py:260` — `SwapAlternative` con nombre y macros |
| **B7** | No había forma de convertir un análisis en registro | `vision/presentation/router.py` — `POST /logs/food/jobs/{id}/confirm` |
| **BE-11** | Porción ajustable | `plan/presentation/router.py:907` — `PATCH …/portion` |
| **B1** | `GET /me/weight-goal` 500 sin pesajes | `tests/unit/profile/test_weight_goal_null_guard.py` |
| **A1** | `complete` duplicaba filas en `food_logs` | `tracking/event_handlers.py:39` — `ON CONFLICT (user_id, idempotency_key)` |
| **B3** | `slope_kg_per_week` viajaba como string | `nutrition/presentation/router.py` — ahora `float(...)` |
| **C13** | El rango de kcal de visión no se emitía | `vision/presentation/schemas.py` — `kcal_min/max`, `total_kcal_min/max` |
| **C16** | `starting_weight_kg` no llegaba en el perfil | `profile/presentation/router.py` |

## 1.b Lo que estaba resuelto desde antes y seguíamos pidiendo (10)

Esto es culpa nuestra por no verificar. Lo listamos con la evidencia para cerrarlo formalmente.

| # | Lo que decíamos | Lo que encontramos al comprobarlo |
|---|---|---|
| **C1** | "¿`/plan` sigue emitiendo `instructions_localized`?" | **Sí.** `plan/presentation/schemas.py:118` lo declara y `router.py:307` lo llena. Además se deriva con fallback: `instructions_translations.get(locale) or instructions_en` (`router.py:258`), así que un idioma sin traducir cae a inglés en vez de quedarse vacío. **Era nuestro punto rojo y no existía.** |
| **C7** | "`GET /me` no trae 4 campos del formulario" | Los trae **todos**: `dietary_pattern`, `bodyfat_pct`, `trimester`, `is_exclusively_breastfeeding`, más `goal_weight_kg` y `starting_weight_kg`. Verificado dentro de `ProfileResponse`. El prefill incompleto es trabajo **nuestro**. |
| **B2** | "Persistan el perfil antes de generar el plan" | Hecho desde el 2026-06-09: `POST /me/onboarding` es guardado de perfil y nada más; el plan lo pide el cliente aparte (`profile/presentation/router.py:3-9`). |
| **B10** | "`MealCompleted` no escribe `food_log`" | Sí escribe: `tracking/event_handlers.py:22-45`, con `ON CONFLICT`. |
| **B8** | "`/logs/food/{id}/edit` no corrige el registro que nombra" | Ahora sí: `vision/presentation/router.py:488-534` recalcula macros por regla de tres y hace `UPDATE food_logs`. |
| **B9** | "`meal_day_in_future` sin entrada i18n" | Está en el catálogo: `core/problem_details.py:184`. |
| **B12** | "Los errores llegan solo en inglés" | `core/problem_details.py` resuelve locale por petición (`_request_locale`, `resolve_locale`). |
| **B4** | "Mirar y comer comparten el cubo de cuota" | `vision/presentation/router.py:86` — `_check_rate_limit(user_id, persist=persist)`. |
| **C15** | "`complete` acepta días futuros" | Lo impide: `plan/application/use_cases.py:79` lanza `meal_day_in_future`. Nuestra guarda de cliente ya no es la única. |
| **A2bis.1** | "`grocery_lists` admite dos listas por plan" | `migrations/versions/0048_grocery_list_unique_plan.py` crea el índice único. |

## 1.c Preguntas que se responden solas leyendo su código (2)

| # | Respuesta |
|---|---|
| **C5** | *"¿La migración `0047` afecta a `/logs/fasting`?"* — **Sí, y nos habíamos equivocado al decir que no.** `POST /logs/fasting` escribe en `fasting_sessions` (`tracking/infrastructure/fasting_repository.py:85,104`), que es justo la tabla que `0047` indexa. **Pero el índice no nos permite retirar el pre-GET:** es un índice parcial de "una sesión *abierta* por usuario", y nuestro pre-GET existe para deduplicar el backfill de **ventanas ya cerradas** de hasta tres días atrás, fuera de su caché de idempotencia de 24 h. Lo mantenemos, y ahora sabemos por qué. |
| **C8** | *"¿Cuál es el payload real del 422 `not_food_image`?"* — `vision/application/submit_photo.py:116`: `raise ValidationError(f"not_food_image:{reason}")`. Viaja en el `detail` del problema de validación. Ya podemos dejar de buscar el slug en todos los campos donde podría estar. |

---

# Parte 2 — Abierto. Aquí sí necesitamos algo

Cada punto lleva: **qué falla exactamente**, **qué esperamos**, y **cómo sabremos que está hecho**.

## 🟠 C12 — Los vasos de agua no se guardan en ningún sitio

**Qué falla.** El usuario toca un vaso en Home y el estado vive **solo en memoria del cliente**
(`HomeViewModel.swift:112`). Se pierde al cerrar la app y no existe en ningún otro dispositivo.
Buscamos "slot" y "water_slot" en `app/tracking/` y no hay nada que lo persista.

**Qué esperamos.** Cualquiera de las dos, y la segunda nos vale igual:

- **Opción A** — un endpoint que registre consumo por slot:
  `POST /logs/water` con `{"ml": <int>, "at": <ISO-8601>}`, y que `GET /goals/today` devuelva
  `water_consumed_ml` ya acumulado (como ya hace).
- **Opción B** — confírmennos que basta con acumular mililitros en el consumo de agua que ya existe.
  Entonces el "slot" pasa a ser una vista derivada del total y lo reescribimos nosotros, sin que
  ustedes toquen nada.

**Criterio de aceptación.** Marcar un vaso, cerrar la app, abrirla en otro dispositivo con la misma
cuenta, y ver el vaso marcado.

## 🟠 C18 — Ajustar la porción entrena los planes futuros, y no se puede evitar

**Qué falla.** `PATCH /plans/{id}/meals/{id}/portion` no es una acción local: en la misma transacción
escribe `user_appetite_by_slot` (`plan/presentation/router.py:949-963`), una media rodante por franja
que decide **cuánto se sirve en esa franja en los planes siguientes**.

Consecuencia: quien baja la cena a `0.75` porque hoy no tiene hambre le enseña al motor a servirle
cenas más pequeñas **de forma permanente**. Un ajuste puntual y una preferencia estable entran por la
misma puerta, y el cliente no puede distinguirlas.

**Lo entregamos diciéndolo en la interfaz** —"ajustar esto también nos dice cuánto servirte en esta
franja de aquí en adelante"— porque la alternativa era un plan que encoge sin que el usuario pueda
entender por qué. Pero el copy es un parche sobre un contrato que mezcla dos intenciones.

**Qué esperamos.** Un campo más en el cuerpo:

```json
PATCH /plans/{plan_id}/meals/{meal_id}/portion
{ "user_factor": 0.75, "persist_calibration": false }
```

`true` por defecto, para no cambiarles el comportamiento actual ni romper a nadie.

**Criterio de aceptación.** Con `persist_calibration: false`, `user_appetite_by_slot` no cambia para
ese usuario y esa franja. Comprobable con un `SELECT` antes y después.

## 🟡 C6-b — `tags` existe en el contrato, falta el catálogo

**Corrección nuestra:** decíamos que `tags` no estaba en el contrato. **Sí está**:
`plan/presentation/schemas.py:125`, dentro de `PlanMealResponse`. La petición se reduce a lo que falta
para poder pintarlos.

**Qué falla.** Recibimos una lista de slugs (`"muscle-gain"`) sin lista cerrada ni traducción. El
cliente tiene prohibido inventar etiquetas, así que hoy los decodificamos y no los mostramos.

**Qué esperamos.** Una de las dos:
- la lista canónica cerrada de slugs con su `es`/`en`, en el catálogo i18n que ya usan para los
  errores (migración `0051` es exactamente el mecanismo); **o**
- que `tags` viaje ya localizado, como hacen con `name_localized`.

**Criterio de aceptación.** Un slug nuevo por su parte aparece traducido sin que iOS publique versión.

## 🟡 C14 — `error_code` de visión es el nombre de una clase de Python

**Qué falla.** `vision/application/process_vision_job.py:592`:

```python
err_code = exc.__class__.__name__
```

Eso llega al cliente en `error_code`. No es un slug estable: cambia si renombran una excepción, y no
tiene entrada en el catálogo i18n. Nuestro mapeo devuelve `nil` siempre
(`FoodAnalysisViewModel.swift:586-590`), así que **el usuario ve un mensaje genérico cada vez que la
visión falla**, sin importar el motivo.

La migración `0051` sembró i18n para reglas de negocio, pero no para estos.

**Qué esperamos.** Un catálogo cerrado de slugs para los fallos de visión, con la misma forma que
`not_food_image`, y sembrado en `error_i18n`. Con cuatro o cinco cubre el 95 %:
`vision_provider_unavailable`, `vision_timeout`, `vision_image_unreadable`, `vision_cost_cap`,
`vision_internal`.

**Criterio de aceptación.** `error_code` es uno de un conjunto cerrado y documentado, y cada valor
tiene traducción `es`/`en`.

## 🟡 C19 — Los ingredientes no reflejan el `user_factor`

**Qué falla.** Con la porción a `0.5`, los macros efectivos llegan a la mitad —correcto— pero la lista
de ingredientes sigue diciendo "150 g de pollo". `AdjustPortion` aplica el factor a los macros
(`plan/application/use_cases.py:85-86`) y no toca `plan_meal_ingredients`.

El usuario ve una receta que dice una cosa y unos macros que dicen otra. **No lo escalamos en el
cliente**: inventar gramos es exactamente lo que prohíbe la regla de cero campos fantasma, y sería la
misma clase de error que multiplicar dos veces los macros.

**Qué esperamos.** Una de las dos:
- `amount_g_effective` por ingrediente en la respuesta del PATCH; **o**
- confirmación explícita de que la lista describe **la receta base** y no la ración, y entonces lo
  decimos en la interfaz.

**Criterio de aceptación.** A factor `0.5`, o los gramos se muestran a la mitad, o la pantalla explica
que la receta es la base.

## 🟡 C20 — `is_adjusted` se escribe y no se devuelve

**Qué falla.** `tracking/event_handlers.py` guarda `is_adjusted` en `food_logs` (BE-11), pero ninguna
respuesta lo expone — buscado el campo en todos los esquemas de `app/`. El historial no puede
distinguir una comida entera de una a media ración, que es justo lo que el campo existe para saber.

**Qué esperamos.** El campo en las lecturas de `food_logs` (`GET /logs/food/...`). Es un `SELECT` más.

**Criterio de aceptación.** Una comida registrada con `user_factor != 1` llega al historial con
`is_adjusted: true`.

## 🟡 C17 — `/advance` no honra `Idempotency-Key`

**Qué falla.** `advance_plan` (`plan/presentation/router.py:870-876`) no declara el header, a
diferencia de `create_plan`, que sí lo toma. iOS lo manda como higiene y se ignora: un reintento de
red sobre `REGENERATE` o `CANCEL` se aplica dos veces.

**Qué esperamos.** El mismo `require_idempotency_key` que ya usan en `create_plan`, o al menos
tolerar y deduplicar la clave.

**Criterio de aceptación.** Dos `POST /advance` idénticos con la misma clave producen un solo efecto.

## 🟠 A2.1 — El `available` del ayuno sigue siendo fail-open

**Qué falla.** `tracking/presentation/goals_today.py:118`:

```python
fasting_block: dict = {"available": True}
try:
    ...
except Exception:
    pass
```

Ese `True` no es "el default de la regla": es **lo que se envía cuando la consulta de elegibilidad
falla**, porque todo el bloque vive dentro del `try`. Un fallo suyo ofrece ayuno a alguien que podría
estar excluido por embarazo o lactancia.

**Qué esperamos.** Que la clave **no viaje** cuando no se pudo resolver:

```python
fasting_block: dict = {}          # sin "available"
try:
    fasting_block["available"] = await fasting_available_for(session, current_user)
    ...
except Exception:
    pass                          # la clave no viaja
```

Ausencia = "no pude saberlo, deja las cosas como están". `false` = "la regla dijo que no". Hoy `true`
significa dos cosas a la vez. **Parche listo para aplicar:**
`docs/backend/C0-fasting-available-absent.patch`, verificado con `git apply --check` sobre su HEAD.

**Por qué no es urgente:** nuestro cliente ya está blindado — un `false` remoto sin confirmación del
perfil oculta la superficie pero **no** desmonta la ventana del usuario ni escribe en el servidor.

**Criterio de aceptación.** Con la consulta de elegibilidad fallando, la respuesta de
`GET /goals/today` no incluye la clave `available`.

## 🟡 B5 — El OpenAPI no está publicado

**Qué falla.** Verificado hoy contra PROD, con UA de Nova:

```
GET https://api.ms-tech-stack.cloud/openapi.json  → 404
```

No es un problema de permisos: no está publicado. Mientras tanto integramos leyendo su Python, que es
literalmente cómo se colaron los desajustes que este documento lleva corrigiendo todo el día.

**Criterio de aceptación.** `GET /openapi.json` responde 200 en producción.

## 🟡 A2bis.5 — Pregunta: ¿puede el worker reprocesar un job ya persistido?

Es la única pregunta que nos queda sin poder responder desde su código. Si `persist_food_logs` puede
ejecutarse dos veces sobre el mismo job, es un defecto de la misma familia que A1. Si no, no es nada.

## 🟡 A2bis.2 / .3 / .4 — Idempotencias menores

`POST /grocery-items` sin `Idempotency-Key`; el registro de agua del coach sin idempotencia;
`POST /progress/photos` sin deduplicar pese a tener ya el hash. Ninguna nos bloquea.

## 🟡 C9 — 6 recetas sin `recipe_components`, y ahora sabemos qué le pasa al usuario

Su backlog ya lo tenía. Añadimos la consecuencia exacta, que no era obvia: en `router.py:273`, cuando
no hay fila de datos de receta, `instructions = []`. Esas recetas llegan **sin instrucciones**, y
nuestra pantalla oculta la sección cuando el array viene vacío. El usuario ve una receta sin pasos y
no hay ningún error en ningún lado.

## 🟡 C10 · BE-10 · BE-13 · BE-14 — Sin prisa

Leak de disco al borrar/reemplazar imagen (su backlog). P50/P95 real del job de visión y garantía de
estado terminal. Regenerar día y favoritos, sin implementación y sin urgencia por nuestra parte.

## ❔ A2.4 — Su suite de tests

Lo reportamos en el informe del 24 y **hoy no hemos podido verificarlo**: al intentar recolectar los
tests en nuestra copia salen 198 errores de importación, que casi seguro son de nuestro entorno y no
de su CI. Lo decimos en vez de repetir la afirmación sin comprobarla.

---

# Cómo se hizo este barrido

Para que puedan juzgar el alcance en vez de fiarse de nuestra palabra. Se recorrió el cliente entero
con estos criterios, y **cada resultado se fue a verificar a su repositorio** antes de escribirlo:

1. Campos de DTO documentados como "`nil` hasta que backend lo emita".
2. Comentarios que nombran una ausencia del backend (`no endpoint`, `not documented`, `until backend`).
3. `TODO(contract)` y toda deuda de backend citada en el código.
4. Estado que el cliente guarda solo en memoria por no tener dónde persistirlo.
5. Guardas de negocio que viven únicamente en el cliente.
6. Escrituras sin idempotencia server-side.
7. Workarounds vigentes, leídos contra sus tres handoffs de agosto.

**Fuera de alcance, y lo decimos para que no se lea como un hueco suyo:** 18 casos de `Endpoint`
declarados en nuestro cliente sin ningún consumidor (`billing*`, `progressPhotos*`, `meExport`,
`recipesSemanticSearch`, `groceryListShare`…). Es deuda **nuestra** y la resolvemos nosotros.
