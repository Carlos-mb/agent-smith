Una tarea SWE-bench sigue este recorrido:

```text
CLI
  -> carga la tarea
  -> prepara proveedor LLM
  -> crea contenedor Docker
  -> inicia servidor MCP
  -> inicia sandbox
  -> bucle Thought -> Code -> Observation
  -> obtiene el diff
  -> limpia recursos
  -> escribe solution.json
```

## 1. Entrada del programa

Empieza en `main()` de `agent_swebench.py`.

Puedes abrirlo con `Ctrl+P` y escribir:

```text
student/agent_swebench.py
```

Después busca `def main`.

El programa recibe:

```bash
uv run python -m agent_swebench \
  --task-file tarea.json \
  --output solucion.json \
  --model-name nombre-del-modelo \
  --provider-url https://...
```

`parse_arguments()` lee esos argumentos. Después `main()`:

1. Carga el JSON de la tarea.
2. Lo valida como `SWEBenchTaskInput`.
3. Llama a `run_swebench_agent(...)`.
4. Guarda el resultado final en el fichero indicado por `--output`.

La validación del modelo está definida en `models.py`, en `SWEBenchTaskInput`.

## 2. Preparación del agente

El siguiente paso está en `run_swebench_agent()` dentro de `swebench_agent.py`.

Esta función prepara todo lo necesario para resolver una tarea:

- límites de tiempo e iteraciones;
- cliente del proveedor LLM;
- contenedor Docker;
- servidor MCP;
- sandbox;
- bucle principal del agente.

Primero construye los límites mediante `_build_swebench_limits()`:

- máximo de 30 iteraciones;
- máximo de 300.000 tokens de entrada;
- máximo de 10.000 tokens de salida;
- máximo de 900 segundos.

## 3. Preparación del modelo LLM

`run_swebench_agent()` llama a:

```python
ProviderClient.from_environment(...)
```

La implementación está en `providers.py`.

Busca en la configuración una entrada que coincida con:

- URL del proveedor;
- nombre del modelo.

Después obtiene las claves API desde variables de entorno.

El modelo todavía no recibe la tarea en este momento. Sólo se prepara el cliente que hará las peticiones posteriores.

Cada llamada al modelo ocurre en `ProviderClient.complete()`.

Esa función:

1. Envía el historial al proveedor.
2. Mide los tokens usados.
3. Controla los reintentos.
4. Puede rotar entre varias claves si recibe un `429`.
5. Devuelve el texto producido por el modelo y sus métricas.

## 4. Creación del contenedor Docker

La clase `SWEEnvironment`, en `swebench_agent.py`, representa el entorno de la tarea.

Su método `start()`:

1. Comprueba si existe la imagen Docker.
2. La descarga si es necesario.
3. Arranca un contenedor con el repositorio en `/testbed`.
4. Desactiva la red con `--network none`.
5. Comprueba que existe `/testbed`.

El contenedor se mantiene vivo usando:

```bash
docker run ... image cat
```

El proceso Python conserva abierto `stdin`. Cuando el agente termina o muere, ese canal se cierra y el contenedor puede terminar y eliminarse.

El modelo trabaja conceptualmente sobre:

```text
/testbed
```

Ahí están el código del proyecto y sus tests.

## 5. Inicio del servidor MCP

Después se crea un `MCPClient`, definido en `mcp_client.py`.

El servidor que se arranca es:

`mcp_tools_swebench.py`

Se ejecuta mediante transporte `stdio`. El servidor ofrece herramientas como:

- `read_file`;
- `edit_file`;
- `list_files`;
- `search_code`;
- `find_references`;
- `run_command`;
- `run_tests`;
- `get_patch`.

`MCPClient.start()` conecta con el servidor y descubre sus herramientas mediante `_discover()`.

Después construye un manual textual para el modelo. Ese manual explica qué herramientas existen y qué parámetros reciben.

Antes de continuar, el programa comprueba que están disponibles todas las herramientas obligatorias.

## 6. Construcción de las instrucciones

Hay dos textos importantes en `swebench_agent.py`.

### Prompt del sistema

`build_swebench_system_prompt()` explica al modelo:

- que debe usar `Thought -> Code -> Observation`;
- que sólo se ejecutará código Python dentro de un bloque;
- que debe leer antes de editar;
- que debe usar `edit_file`;
- que debe ejecutar `run_tests`;
- que no debe llamar a `final_answer` antes de obtener un diff real.

También incluye el manual MCP descubierto anteriormente.

### Prompt de la tarea

`build_swebench_task_prompt()` convierte la tarea en un texto con:

- identificador;
- repositorio;
- descripción del problema;
- posibles pistas;
- ubicación `/testbed`.

## 7. Inicio del sandbox

Se crea `SandboxSession`, definida en `sandbox_session.py`.

Su método `start()` inicia un proceso separado usando `multiprocessing`.

Esto es importante:

- el código generado por el modelo no se ejecuta en el proceso que contiene las claves API;
- el trabajador tiene un namespace persistente;
- las variables creadas en una iteración pueden existir en la siguiente;
- si una ejecución supera el tiempo permitido, se mata el trabajador.

El sandbox aplica restricciones de imports, builtins, memoria, tiempo y acceso a ficheros.

## 8. Comienzo del bucle principal

El flujo llega a `run_agent_loop()` en `agent_loop.py`.

Aquí se crean inicialmente dos mensajes:

```text
system: instrucciones del agente
user: descripción de la tarea
```

Después comienza el ciclo:

```text
Thought -> Code -> Observation
```

En cada iteración se hace lo siguiente.

## 9. Envío del historial al modelo

El bucle calcula cuánto presupuesto de tokens queda y llama a:

```python
provider.complete(...)
```

Antes de enviarlo, `trim_history()` reduce el historial si es demasiado grande.

Conserva:

- el prompt del sistema;
- la tarea original;
- suficientes intercambios recientes para que el modelo recuerde lo que está haciendo.

Después el proveedor devuelve la respuesta del modelo.

Esa respuesta suele tener esta forma:

```text
Thought: Buscaré la definición de la función.

```python
print(search_code(pattern="..."))
```

<end_code>
```

## 10. Extracción del código Python

El texto del modelo pasa por `extract_agent_code()` en `code_extraction.py`.

Esta función:

1. Busca bloques cerrados de Python.
2. Comprueba que el código tiene sintaxis válida.
3. Busca un bloque que llame a una herramienta MCP.
4. Si el modelo usó formatos como `<tool_call>` o `<tool_use>`, los convierte en llamadas Python.
5. Si no encuentra código válido, devuelve una observación de error al modelo.

Por ejemplo, convierte conceptualmente:

```text
<tool_call>
read_file
<arg_key>filepath</arg_key>
<arg_value>/testbed/app.py</arg_value>
</tool_call>
```

en:

```python
print(read_file(filepath="/testbed/app.py"))
```

## 11. Ejecución del código en el worker

El código extraído se envía a:

```python
sandbox.execute(code)
```

en `sandbox_session.py`.

El worker ejecuta el bloque en `execute_block()`, dentro de `sandbox.py`.

El worker:

1. Analiza el código con `ast.parse`.
2. Lo ejecuta con `exec`.
3. Captura stdout y stderr.
4. Conserva las variables entre bloques.
5. Devuelve la salida al agente.

El modelo no puede importar directamente el proyecto desde el sandbox. Para trabajar con el repositorio debe usar las herramientas MCP.

## 12. Llamada a una herramienta MCP

Cuando el código generado contiene, por ejemplo:

```python
print(read_file("/testbed/foo.py", 10, 40))
```

la función `read_file` del sandbox no lee directamente el fichero.

Es un wrapper que envía una petición al proceso MCP:

```text
worker
  -> SandboxSession
  -> MCPClient
  -> servidor mcp_tools_swebench.py
  -> swebench_tools.py
```

La implementación real está en `swebench_tools.py`.

Por ejemplo:

- `read_file()` lee líneas numeradas;
- `search_code()` busca expresiones regulares;
- `edit_file()` sustituye un texto único;
- `run_command()` ejecuta un comando en `/testbed`;
- `run_tests()` ejecuta los tests;
- `get_patch()` ejecuta `git diff`.

## 13. Lectura del código

Normalmente el modelo comienza usando:

```python
search_function_or_class_definition_in_code(...)
```

o:

```python
search_code(...)
```

Después usa:

```python
read_file(...)
```

El prompt obliga al modelo a leer el código antes de editarlo.

La aplicación no decide qué función concreta debe investigar. El modelo lo decide a partir de la descripción del issue y de las observaciones obtenidas.

## 14. Edición del repositorio

El modelo edita con:

```python
edit_file(
    filepath="/testbed/...",
    old_str="...",
    new_str="...",
)
```

`edit_file()` sólo acepta el cambio si:

- `old_str` aparece exactamente una vez;
- el cambio realmente modifica el archivo;
- si es Python, el resultado sigue compilando.

La edición real se implementa en `swebench_tools.py`, mediante un pequeño programa Python ejecutado en el contenedor.

## 15. Ejecución de tests

Después de editar, el modelo debe llamar a:

```python
run_tests()
```

La implementación ejecuta el `eval_script` asociado a la tarea.

La salida incluye:

- código de salida;
- stdout;
- stderr;
- resultado de los tests.

Si fallan, esa salida se convierte en la siguiente `Observation`, y el modelo puede corregir el código en otra iteración.

## 16. Construcción de la observación

`build_observation()` en `agent_loop.py` combina:

- feedback del extractor;
- salida impresa por el bloque;
- errores;
- timeouts;
- posible respuesta final.

Después añade esa observación al historial:

```text
assistant: respuesta anterior del modelo
user: Observation: resultado real
```

La siguiente llamada al modelo recibe ese contexto.

## 17. Obtención del patch

Cuando el modelo considera que el problema está resuelto, debe llamar primero a:

```python
get_patch()
```

`get_patch()` devuelve:

```bash
git diff
```

sin truncarlo.

El prompt exige que el modelo compruebe que el diff existe antes de finalizar.

## 18. Finalización con `final_answer`

Finalmente el modelo genera algo como:

```python
final_answer(get_patch())
```

`final_answer()` está definido localmente en `sandbox.py`.

No es una herramienta MCP.

La función lanza una excepción especial, `FinalAnswerSignal`, que transporta el texto del diff hasta `SandboxSession`.

El bucle detecta que existe `execution.final_answer` y marca la tarea como correcta provisionalmente.

## 19. Comprobación final del diff

Al volver a `run_swebench_agent()`, se verifica que la respuesta contiene:

```text
diff --git
```

Esto evita aceptar como solución algo como:

```text
No changes yet.
```

Si el modelo no modificó ningún fichero, el resultado se marca como fallido.

## 20. Limpieza de recursos

Finalmente siempre se ejecuta el bloque `finally` de `run_swebench_agent()`.

Se cierran, en este orden:

1. `SandboxSession`;
2. `MCPClient`;
3. contenedor Docker.

También se registra el tiempo total y cualquier error de limpieza.

## 21. Escritura del resultado

Por último, `main()` escribe `SolutionOutput` en el fichero indicado por `--output`.

Ese JSON contiene, entre otros datos:

- `success`;
- `solution`, que contiene el diff;
- número de iteraciones;
- peticiones al modelo;
- tokens usados;
- tiempos;
- prompts;
- métricas de cada paso;
- error, si lo hubo.

La aplicación termina aquí. La validación oficial posterior la realiza `moulinette`, no el propio agente. El agente entrega el patch; `moulinette` comprueba después si ese patch soluciona realmente la tarea.

Created 4 todos