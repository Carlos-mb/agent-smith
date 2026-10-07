# Cómo funciona un ciclo MBPP en Agent Smith — explicación consolidada

> **Nota (7 de octubre de 2026).** Escrito el 12 y 13 de septiembre, antes de la reorganización
> del 17 de septiembre. `json_worker.py` ya no existe: el trabajador es `worker_main`, en
> `agent_smith/sandbox.py`, y habla con el agente por una tubería de `multiprocessing` en lugar
> de por su salida estándar. La idea de los *wrappers* sigue igual. La explicación al día está en
> `GUIDE.md`, secciones 15 y 16.

Documento de estudio con el ejemplo de "sumar dos números", pensado para defender
la arquitectura ante un evaluador que pregunte "explícame qué pasa aquí".

---

## 1. El JSON de entrada (`MBPPTaskInput`)

```json
{
  "task_id": 42,
  "task_definition": "Write a function to add two numbers.",
  "function_definition": "def add(a, b):",
  "test_imports": [],
  "test_list": [
    "assert add(2, 3) == 5",
    "assert add(-1, 1) == 0",
    "assert add(10, 15) == 25"
  ]
}
```

**Dato clave que se ve solo si miras la moulinette (`moulinette/mbpp/interact.py`):**
la moulinette se queda con el **primer test** (`assert add(2, 3) == 5`) y solo le
pasa al agente el resto:

```python
public_test_list = ["assert add(-1, 1) == 0", "assert add(10, 15) == 25"]
```

El agente **nunca ve** ese primer test. Se usa más adelante, en una validación
independiente. Esto no es un despiste — es la forma de comprobar que el agente
resolvió el problema de verdad, y no solo "aprobó por suerte" los tests que veía.

---

## 2. Los dos prompts que se generan (no es uno solo)

**System prompt** (fijo, casi independiente de la tarea — `build_mbpp_system_prompt`):
metodología Thought → Code → Observation, formato exigido (bloque ` ```python ` +
`<end_code>`), un ejemplo de juguete, y al final el **manual MCP**, que lista las
herramientas disponibles (para MBPP, solo `run_tests`).

**Task prompt** (variable, generado del JSON — `build_mbpp_task_prompt`):

```
Task 42
Write a function to add two numbers.
Required signature: def add(a, b):
These public test variables are already defined in your worker:
test_imports = []
test_list = ['assert add(-1, 1) == 0', 'assert add(10, 15) == 25']
```

Nota: `test_imports`/`test_list` **ya están precargados como variables** en el
worker antes de la primera llamada al LLM — el modelo las referencia por nombre,
no las reescribe.

---

## 3. El LLM no devuelve "solo código"

La respuesta debe seguir un formato exigido: un `Thought` breve, un bloque cerrado
` ```python ... ``` `, y `<end_code>`. El programa tiene que **extraer** ese bloque
(`extract_agent_code`) antes de poder ejecutarlo — si el modelo no respeta el
formato, el sandbox debe avisarle explícitamente (nunca dejarlo "adivinando" qué
pasó).

---

## 4. Ejemplo completo con más de un intento (bug → corrección → entrega)

### Iteración 1 — el LLM comete un error (resta en vez de suma)

```
Thought: I will check my candidate against the supplied assertions.
```python
solution = r"""def add(a, b):
    return a - b
"""
print(run_tests(code=solution, test_imports=test_imports, test_list=test_list))
```
<end_code>
```

- **Sandbox**: ejecuta este bloque. Solo crea la variable `solution` (un *string*,
  no una función ejecutada) y llama al *wrapper* local `run_tests`.
- **Docker**: se construye el programa real (`test_imports` + código + `test_list`)
  y se ejecuta en un contenedor nuevo. `add(-1, 1)` da `-2` → `AssertionError` →
  `exit_code != 0`. El contenedor se destruye al terminar.
- **Observation** que recibe el LLM:
  ```
  {'success': False, 'message': 'Public tests failed.',
   'output': 'Traceback...\nAssertionError', 'exit_code': 1}
  ```

### Iteración 2 — el LLM corrige el bug

```
Thought: Subtraction was wrong; addition is required. Retesting with the fix.
```python
solution = r"""def add(a, b):
    return a + b
"""
print(run_tests(code=solution, test_imports=test_imports, test_list=test_list))
```
<end_code>
```

- **Sandbox**: mismo proceso, mismo `namespace` — sobrescribe `solution`.
- **Docker**: contenedor **nuevo** (el anterior ya no existe). Ambos asserts
  pasan → `exit_code == 0`.
- **Observation**: `{'success': True, 'message': 'All public tests passed.', ...}`

### Iteración 3 — el LLM entrega la solución

```
Thought: Public tests passed; submitting the final solution.
```python
final_answer(solution)
```
<end_code>
```

- **Sandbox**: ejecuta `final_answer(solution)`. **No hay Docker aquí.**
  `final_answer` es una función puramente local del sandbox (no es herramienta
  MCP): lanza `FinalAnswerSignal`, capturada por `execute_block`, que la
  convierte en un mensaje `done` de vuelta al coordinador.

### Tabla resumen

| Iteración | ¿Sandbox? | ¿Docker? | Resultado |
|---|---|---|---|
| 1 | Sí (crea `solution` con bug, llama `run_tests`) | Sí (contenedor #1, falla) | `Observation` con el error real |
| 2 | Sí (sobrescribe `solution` corregido) | Sí (contenedor #2, pasa) | `Observation` de éxito |
| 3 | Sí (`final_answer`) | No | Fin del bucle |

Totales: **1 sandbox** (mismo proceso las 3 veces) + **2 contenedores Docker**
(uno por cada llamada real a `run_tests`, desechado tras su uso).

---

## 5. Validación final: la moulinette, aparte y con un test que el agente no vio

Después de que `main()` escriba `solution.json` (con `success=True` y el código
corregido), un paso **totalmente aparte** (`moulinette_eval validate mbpp ...`)
vuelve a ejecutar la solución final, esta vez contra el test que se había ocultado
al principio:

```python
assert add(2, 3) == 5   # 2 + 3 == 5 → True
```

**El `success: True` que escribe el agente es solo su propia opinión**, basada en
tests públicos. La nota real la decide la moulinette, con un test que el agente
nunca vio — así se detecta si el agente "hizo trampa" o tuvo suerte en vez de
resolver el problema general.

---

## 6. Sandbox vs. Docker: dos capas de seguridad distintas, para dos códigos distintos

| | **Sandbox** (`json_worker.py`) | **Docker** (contenedor de `run_tests`) |
|---|---|---|
| ¿Qué ejecuta? | El código de *orquestación* del LLM (crear `solution`, llamar herramientas) | Solo la solución candidata + los asserts públicos |
| ¿Cuánto vive? | Un proceso, toda la tarea | Uno nuevo por cada llamada a `run_tests`, desechado después |
| ¿Qué lo protege? | Lista blanca de imports, builtins restringidos, rutas permitidas, timeout, memoria | Aislamiento de Docker: sin red, memoria/CPU limitadas |
| ¿Por qué esa capa y no otra? | El código de orquestación es predecible y necesita muy pocos imports | La solución puede necesitar cualquier import de la tarea; no se puede limitar de antemano |

**Dato clave**: la solución candidata (`solution`) **nunca se ejecuta dentro del
sandbox**. Es solo una cadena de texto hasta que `run_tests` la manda a Docker.
El propio system prompt lo pide explícitamente: *"Do not also define the function
in the worker."*

**Por qué hacen falta las dos capas y no solo una:**
- Imports incompatibles: el sandbox necesita una lista blanca corta y fija; la
  solución puede necesitar cualquier módulo de la tarea.
- Los "trucos" en Python (interceptar `__import__`, restringir `builtins`) son
  más débiles que el aislamiento a nivel de sistema operativo que da Docker.
- Si el código de la solución se cuelga, Docker se destruye sin coste; si el
  *worker* del sandbox se cuelga, hay que matarlo (`terminate` → `kill`), lo cual
  es más costoso porque es tu propio proceso persistente.

**Corrección importante sobre "seguridad por pedir amablemente":** el sandbox no
es seguro porque "solo le pedimos que defina `solution` y llame a `run_tests`".
El LLM podría ignorar esa instrucción y escribir `import os; os.system(...)`.
Lo que de verdad lo impide es la **restricción técnica impuesta por el sandbox**
(ver sección 8), que actúa exista o no la buena voluntad del modelo. El prompt
educa sobre el comportamiento esperado; el sandbox impone lo que es posible.

**Corrección sobre "Docker hace que no pase nada":** Docker contiene y acota el
riesgo (sin red, memoria/CPU limitadas, contenedor desechable), pero no es una
garantía absoluta al 100% — es defensa en profundidad, no una caja infalible.

---

## 7. MCP: quién es cliente, quién es servidor, y qué pasa por los pipes

- **Servidor** (`mcp_tools_mbpp.py`, con `FastMCP`): expone herramientas
  (`run_tests`) y espera peticiones. Usa el decorador `@mcp.tool()` para
  registrarse.
- **Cliente** (`MCPClient`, con `ClientSession` del SDK): inicia la conversación
  — `initialize()`, pide la lista de herramientas, luego `call_tool(...)`.

El nombre `MCPClient` describe el **rol en el protocolo**, no quién arrancó a
quién: aunque esa clase también lance el proceso del servidor (por conveniencia
de arquitectura), sigue siendo el "cliente" en la conversación MCP — igual que
un navegador sigue siendo cliente HTTP aunque también arrancara el servidor web.

**`await client.start(deadline=deadline)`** no es un simple "lánzalo y sigue": es
un *handshake* completo y bloqueante — arranca el proceso, abre la `ClientSession`,
manda `initialize()`, descubre herramientas/recursos/prompts, construye el
`MCPManual` — y solo entonces devuelve `(session, manual)`.

**Los *pipes* de stdin/stdout no son la consola que ves.** Son tuberías privadas
entre tu proceso padre y el proceso hijo (el servidor MCP), invisibles para ti
como usuario:
- `print()` del **cliente** (tu proceso principal): aparece en consola con
  normalidad, no hay pipe de por medio.
- `print()` a `stdout` del **servidor MCP**: nunca aparece en consola — se cuela
  como bytes dentro del canal del protocolo JSON-RPC y **rompe el parseo**.
- `print()`/logs a `stderr` del servidor: sí llegan a la consola (o al fichero de
  log si rediriges), porque `stdio_client(parameters, errlog=sys.stderr)` conecta
  el `stderr` del hijo directamente al `stderr` del padre. Por eso el logging del
  proyecto va siempre a `stderr`, nunca a `stdout` — ese canal está reservado
  para el protocolo.

---

## 8. Cómo se intercepta `__import__` (lo que de verdad protege el sandbox)

Cuando escribes `import os`, Python internamente llama a la función `__import__`,
que es un `builtin` sustituible. El sandbox aprovecha esto:

```python
def _make_safe_import(authorized_imports):
    allowed_imports = tuple(authorized_imports)

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        if not _is_import_allowed(name, allowed_imports):
            raise ImportError(f"Import not allowed: {name}")
        return builtins.__import__(name, globals, locals, fromlist, level)

    return restricted_import
```

Esa función se instala en el diccionario de `builtins` que se le pasa al
`exec()` del código del LLM:

```python
safe["__import__"] = _make_safe_import(config.authorized_imports)
```

Cuando el código del LLM ejecuta `import os`, Python busca `__import__` en *ese*
`namespace` concreto y encuentra `restricted_import`, que rechaza `"os"` (no está
en la lista blanca) **antes** de que el import real ocurra. Esto no afecta al
resto de tu programa — solo al `namespace` aislado de ese `exec()` en concreto.

---

## 9. Qué es un "wrapper generado dinámicamente"

Es una función que **no existe escrita en ningún archivo** — se construye en
tiempo de ejecución, a partir de los datos de cada herramienta MCP descubierta,
no de código fuente fijo:

```python
def _make_tool_wrapper(tool, input_stream, output_stream):
    def tool_wrapper(*args, **kwargs):
        # empaqueta args/kwargs, manda mensaje al coordinador, espera respuesta
        ...
    return tool_wrapper
```

Y la parte realmente dinámica, dentro de un bucle sobre las herramientas
descubiertas:

```python
namespace[name] = _make_tool_wrapper(tool, input_stream, output_stream)
```

Nadie escribió `namespace["run_tests"] = ...` a mano. Si el servidor conectado
fuera otro completamente distinto (recuerda: *"the system will be tested with an
unknown MCP server"*), este mismo bucle generaría los wrappers que hicieran
falta, con los nombres que ese servidor anuncie, sin cambiar una sola línea de
código.

**Diferencia con el decorador `@mcp.tool()`:** el decorador (lado servidor) es
estático — se escribe una vez, en el código fuente. El wrapper (lado sandbox) es
dinámico — se genera en un bucle, a partir de lo que el servidor anuncie en ese
momento.

---

## 10. Por qué usar un `*` (keyword-only) en `run_mbpp_agent(task, args, *, started_at)`

El `*` obliga a que `started_at` se pase por nombre, no por posición — evita que
alguien cuele por error un argumento en la posición equivocada sin que Python
avise. No cambia nada en las llamadas que ya usan `started_at=...`; solo cierra
la puerta a llamarlo posicionalmente en el futuro. Es sintaxis estándar de Python
(PEP 3102), no una decisión de arquitectura sofisticada.

---

## 11. Por qué se usa `asyncio` (y por qué no es una exigencia del enunciado)

El SDK oficial de MCP (`ClientSession`, `stdio_client`, `streamable_http_client`)
es async-only — cada conexión es un *async context manager* y cada llamada es
una corrutina. `asyncio` aparece en el proyecto como consecuencia de usar ese
SDK, no porque el enunciado lo exija.

`asyncio.run(...)` bloquea el hilo que lo llama hasta que la corrutina termina —
es la forma correcta de usar código asíncrono desde un punto de entrada
síncrono. El patrón correcto (el que usa el proyecto) es **un solo
`asyncio.run(...)` por tarea completa**, envolviendo toda la sesión MCP
(conectar → varias llamadas → limpiar) — nunca uno por cada llamada individual,
porque eso rompería la persistencia de la conexión.

El resto del sistema (el *worker* `json_worker.py`, el propio sandbox) se
mantiene totalmente síncrono — `asyncio` se confina a la tarea que sostiene la
sesión MCP, no se propaga a todo el proyecto.

---

## 12. Uso de la IA en este proyecto (para defenderlo si preguntan)

El enunciado no prohíbe que la IA escriba funciones — lo que exige es que el
alumno **entienda, pueda explicar, pueda modificar en vivo, y sea transparente**
sobre el uso de IA (README → sección "Resources"). El criterio no es "quién
tecleó el código", sino si el alumno puede sostener una conversación como esta
sobre cualquier parte de él. Esto es justo lo que la propia guía del enunciado
llama "buena práctica" (usar IA para generar y luego entender/revisar, no para
copiar sin mirar).

---

## Resumen en una frase por concepto

- **JSON de entrada** → datos de la tarea + tests públicos (con uno oculto para la moulinette).
- **Dos prompts** → uno fijo (metodología + manual MCP), uno variable (la tarea concreta).
- **Sandbox** → ejecuta el código de orquestación del LLM; protegido por restricciones técnicas reales, no por buenas intenciones del prompt.
- **Docker** → ejecuta la solución candidata en aislamiento de sistema operativo, desechable tras cada uso.
- **MCP** → protocolo de transporte entre el sandbox y las herramientas; el servidor expone, el cliente pregunta y llama.
- **Wrapper dinámico** → adapta el sandbox a cualquier servidor MCP, sin código fijo por herramienta.
- **Moulinette** → validación final, independiente, con un test que el agente nunca vio.
