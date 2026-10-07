# Flujo completo de una llamada a `run_test()`

> **Nota (7 de octubre de 2026).** Escrito el 12 y 13 de septiembre, antes de la reorganización
> del 17 de septiembre. `json_worker.py` ya no existe: el trabajador es `worker_main`, en
> `agent_smith/sandbox.py`, y habla con el agente por una tubería de `multiprocessing` en lugar
> de por su salida estándar. La idea de los *wrappers* sigue igual. La explicación al día está en
> `GUIDE.md`, secciones 15 y 16.

La idea principal es que el LLM escribe código que parece ejecutar una prueba directamente, pero la función `run_test()` que encuentra el código **no ejecuta realmente la prueba dentro del worker**. Es una función intermedia, llamada *wrapper*, que comunica la petición al exterior.

## 1. El LLM genera código

El LLM puede producir código como:

```python
resultado = run_test(solution)
```

Desde el punto de vista del LLM, `run_test()` es una función disponible que:

1. recibe una solución;
2. ejecuta las pruebas;
3. devuelve el resultado.

Sin embargo, el LLM no necesita conocer los detalles internos de cómo se ejecuta esa función.

---

## 2. El código se ejecuta dentro del worker

El código generado se ejecuta en un proceso Python separado: el **worker**.

Antes de ejecutar el código del LLM, el worker prepara su *namespace*, es decir, el conjunto de nombres y funciones que estarán disponibles para ese código.

En ese namespace existe un nombre llamado:

```python
run_test
```

Pero ese nombre apunta a un **wrapper**, no directamente a la función del servidor MCP.

Conceptualmente:

```text
run_test ─────────► wrapper local del worker
```

Por eso, cuando Python ejecuta:

```python
resultado = run_test(solution)
```

Python sí está ejecutando una función normal. Lo que sucede es que esa función está diseñada para enviar una petición externa, no para ejecutar las pruebas por sí misma.

---

## 3. El wrapper prepara una petición MCP

El wrapper recibe los argumentos de la llamada:

```python
solution
```

Después prepara la información necesaria para solicitar una operación MCP.

La petición contiene, conceptualmente, estos datos:

```text
- tipo de mensaje: mcp_request
- operación: call_tool
- nombre de la herramienta MCP
- argumentos de la herramienta
```

La estructura puede representarse así:

```json
{
  "type": "mcp_request",
  "operation": "call_tool",
  "arguments": {
    "name": "run_test",
    "arguments": {
      "...": "..."
    }
  }
}
```

Este mensaje no significa que la prueba ya se haya ejecutado. Significa:

> “El código que se ejecuta en el worker solicita que el exterior ejecute la herramienta MCP `run_test`”.

---

## 4. El worker envía el mensaje por `stdout`

El worker convierte el mensaje en JSON y lo escribe en su salida estándar, `stdout`.

El mensaje viaja por una comunicación entre procesos:

```text
json_worker.py
      │
      │ stdout
      ▼
sandbox.py
```

El `stdout` no se utiliza aquí solamente para mostrar texto al usuario. También se utiliza como **canal de comunicación estructurado** entre el worker y el controlador del sandbox.

Por eso los mensajes tienen un campo `"type"` que permite distinguirlos:

```text
"type": "output"
"type": "done"
"type": "mcp_request"
"type": "worker_error"
```

En este caso, el controlador detecta:

```text
"type": "mcp_request"
```

---

## 5. El worker queda esperando una respuesta

Después de enviar el mensaje, el wrapper no puede devolver todavía el resultado de `run_test()` porque la prueba aún no se ha ejecutado.

Por eso el worker queda esperando una respuesta por su entrada estándar, `stdin`.

El flujo queda temporalmente detenido en este punto:

```text
LLM code
   │
   ▼
run_test(solution)
   │
   ▼
wrapper
   │
   ▼
envía mcp_request por stdout
   │
   ▼
espera mcp_result por stdin
```

El worker no debe ejecutar directamente la herramienta MCP. Solamente solicita la operación y espera el resultado.

---

## 6. `sandbox.py` recibe el mensaje

El controlador del sandbox lee una línea del `stdout` del worker y la convierte desde JSON a un diccionario Python.

Después examina:

```python
kind = message["type"]
```

Como el valor es:

```text
mcp_request
```

entra en la rama que gestiona las peticiones MCP.

En ese momento, `sandbox.py`:

1. obtiene la operación solicitada;
2. obtiene sus argumentos;
3. utiliza el cliente MCP;
4. envía la petición al servidor MCP.

Es importante distinguir las responsabilidades:

```text
json_worker.py
    Genera la petición MCP.

sandbox.py
    Recibe la petición y la reenvía mediante el cliente MCP.
```

Por tanto, **`sandbox.py` no genera originalmente `mcp_request`; lo recibe**.

---

## 7. El cliente MCP contacta con el servidor MCP

El controlador del sandbox llama al cliente MCP con una operación como:

```text
call_tool
```

El cliente MCP comunica la petición al servidor MCP.

El servidor MCP contiene la implementación real de la herramienta solicitada, por ejemplo:

```text
run_test
```

En este punto ya no estamos ejecutando simplemente el wrapper local del worker. Ahora se está solicitando la operación real al servidor MCP.

---

## 8. El servidor MCP ejecuta la prueba

El servidor MCP recibe la petición y ejecuta la lógica asociada a `run_test`.

En el diseño del proyecto, esa lógica puede:

1. preparar los archivos de la solución;
2. crear un contenedor Docker;
3. introducir en el contenedor el código y las pruebas;
4. ejecutar el comando de pruebas;
5. capturar la salida estándar;
6. capturar la salida de error;
7. obtener el código de salida;
8. construir el resultado de la operación.

Representación simplificada:

```text
Servidor MCP
      │
      ▼
Crea un contenedor Docker
      │
      ▼
Ejecuta la solución y las pruebas
      │
      ▼
Captura stdout, stderr y código de salida
      │
      ▼
Construye el resultado
```

Docker proporciona aquí un entorno separado para ejecutar el código que se está evaluando.

---

## 9. El resultado vuelve al controlador del sandbox

Cuando el servidor MCP termina, devuelve el resultado al cliente MCP.

El recorrido de vuelta es:

```text
Docker
   │
   ▼
Servidor MCP
   │
   ▼
Cliente MCP
   │
   ▼
sandbox.py
```

El controlador del sandbox recibe el resultado de la operación MCP.

Después prepara un mensaje para el worker, conceptualmente parecido a:

```json
{
  "type": "mcp_result",
  "result": {
    "...": "resultado de las pruebas"
  }
}
```

---

## 10. `sandbox.py` envía la respuesta al worker

El controlador escribe el mensaje `mcp_result` en la entrada estándar del worker:

```text
sandbox.py
      │
      │ stdin del worker
      ▼
json_worker.py
```

El worker estaba esperando precisamente esa respuesta.

Al recibirla, la función que había enviado la petición MCP puede continuar su ejecución.

---

## 11. El wrapper devuelve el resultado

El wrapper recibe la respuesta MCP y la transforma en el valor de retorno de la función local.

Así, para el código del LLM, la llamada termina comportándose como una función normal:

```python
resultado = run_test(solution)
```

El valor de `resultado` contiene la información devuelta por la herramienta MCP.

El código del LLM puede entonces hacer algo como:

```python
print(resultado)
```

o analizar el resultado y decidir qué código generar después.

---

# Flujo completo resumido

```text
LLM genera:

    resultado = run_test(solution)
                │
                ▼
Python busca run_test en el namespace del worker
                │
                ▼
Encuentra un wrapper local
                │
                ▼
El wrapper prepara mcp_request
                │
                ▼
json_worker.py escribe mcp_request en stdout
                │
                ▼
sandbox.py recibe el mensaje
                │
                ▼
sandbox.py llama al cliente MCP
                │
                ▼
El cliente MCP contacta con el servidor MCP
                │
                ▼
El servidor MCP ejecuta run_test
                │
                ▼
El servidor crea un Docker y ejecuta las pruebas
                │
                ▼
Captura el resultado
                │
                ▼
El resultado vuelve al cliente MCP
                │
                ▼
sandbox.py recibe el resultado
                │
                ▼
sandbox.py envía mcp_result al worker
                │
                ▼
El wrapper recibe mcp_result
                │
                ▼
El wrapper devuelve el resultado de run_test()
                │
                ▼
El código del LLM recibe:

    resultado
```

## La idea esencial

Hay dos funciones diferentes con el mismo propósito aparente:

```text
run_test del worker
    = wrapper que solicita la operación

run_test del servidor MCP
    = implementación real que ejecuta las pruebas
```

El LLM llama a la primera, pero el resultado procede de la segunda.

Por eso la llamada parece local:

```python
resultado = run_test(solution)
```

aunque internamente implique comunicación entre procesos, una llamada MCP y posiblemente la creación de un contenedor Docker.
