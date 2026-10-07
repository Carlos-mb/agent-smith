> **Nota (7 de octubre de 2026).** Escrito el 12 y 13 de septiembre, antes de la reorganización
> del 17 de septiembre. `json_worker.py` ya no existe: el trabajador es `worker_main`, en
> `agent_smith/sandbox.py`, y habla con el agente por una tubería de `multiprocessing` en lugar
> de por su salida estándar. La idea de los *wrappers* sigue igual. La explicación al día está en
> `GUIDE.md`, secciones 15 y 16.

En nuestor proyecto, cada función MCP se procesa como un wrapper. (Si no recuerdas qué es un wrapper, lo explico más abajo, míralo ahora o te perderás.)
El MCP de MBPP sólo tiene una función, pero el bucle es el mismo. 
El LLM quiere usar las funciones que le hemos dicho que tiene el MCP, como run_test().
Al crear el proceso donde se va a ejecutar el código python, generamos un namespace que contiene esas funciones, como run_test().
Pero esas funciones son run wrapper que se encarga de mandar un mensaje por stdout al sistema que está controlando el Sandobox.
El sistema recive la petición de ejecutar una función del MCP y llama al MCP para que ejecute esa función.
El servidor MCP ejecuta la implementación real de la herramienta, que en el caso de run_test() puede crear un contenedor Docker.
El controlador del Sandbox recibe el resultado, lo envía al proceso que está ejecutando Python y este convierte la respuesta JSON en una respuesta adecuada.
En MBPP sólo tenemos una función, pero el subject dice que debemos estar preparados para más, por eso no lo hacemos una vez, tenemos un bucle que genera un wrapper por cada función del MCP y lo incluímos en el namespace que usa el proceso del Sandbox.

El nombre run_test utilizado por el código del LLM apunta a una función creada por json_worker.py y ejecutada dentro del proceso worker. En este caso, esa función es un wrapper.

El wrapper no ejecuta directamente las pruebas. Recibe los argumentos de la llamada, construye una petición MCP e indica la herramienta que debe ejecutarse, por ejemplo, run_test. Después envía esa petición al controlador del sandbox y espera la respuesta.

El controlador utiliza el cliente MCP para solicitar al servidor MCP la ejecución de la herramienta. El servidor ejecuta la implementación real de run_test, que en el caso de MBPP puede crear un contenedor Docker para ejecutar el código y las pruebas.

# ¿Qué es un wrapper?

Un **wrapper** es una función o clase que se coloca alrededor de otra función, objeto o sistema para ofrecer una forma más sencilla o controlada de utilizarlo.

La palabra *wrapper* significa literalmente **envoltorio**.

La idea es:

```text
Código que utiliza el programa
          │
          ▼
       Wrapper
          │
          ▼
Función o sistema real
```

El código que utiliza el programa no necesita conocer todos los detalles internos. Solo necesita saber:

* cómo llamar al wrapper;
* qué argumentos pasarle;
* qué resultado recibirá.

---

## 1. Ejemplo sencillo en Python

Supongamos que tenemos una función que suma dos números:

```python
def sumar(a, b):
    return a + b
```

Podemos crear un wrapper alrededor de ella:

```python
def wrapper_suma(a, b):
    print("Voy a realizar una suma")
    resultado = sumar(a, b)
    print("La suma ha terminado")
    return resultado
```

Ahora podemos utilizarlo así:

```python
resultado = wrapper_suma(2, 3)
```

El flujo es:

```text
wrapper_suma(2, 3)
       │
       ▼
Muestra un mensaje
       │
       ▼
Llama a sumar(2, 3)
       │
       ▼
Obtiene 5
       │
       ▼
Devuelve 5
```

El wrapper no sustituye necesariamente a la función original. Añade una capa alrededor de ella.

En este ejemplo, el wrapper añade mensajes, pero podría hacer otras cosas:

* comprobar argumentos;
* registrar información;
* controlar errores;
* convertir datos;
* realizar una llamada de red;
* comunicarse con otro proceso;
* ocultar una implementación compleja.

---

# 2. El wrapper puede cambiar completamente lo que ocurre internamente

Un wrapper no tiene que llamar directamente a la función original.

Por ejemplo:

```python
def wrapper_suma(a, b):
    mensaje = {
        "operacion": "sumar",
        "a": a,
        "b": b,
    }

    # Enviar mensaje a otro proceso
    # Esperar respuesta

    return resultado_recibido
```

Para el código que lo utiliza, sigue pareciendo una función normal:

```python
resultado = wrapper_suma(2, 3)
```

Pero internamente puede estar:

* enviando un mensaje;
* esperando una respuesta;
* llamando a otro programa;
* accediendo a un servidor;
* ejecutando una operación en otro ordenador.

El código que llama al wrapper no necesita conocer esos detalles.

---

# 3. Diferencia entre una función real y un wrapper

En el proyecto hay que distinguir dos cosas:

```text
run_test() del worker
    Wrapper local
```

y:

```text
run_test() del servidor MCP
    Implementación real de la herramienta
```

Aunque ambas están relacionadas con la misma operación, no hacen exactamente lo mismo.

## Wrapper del worker

El wrapper:

1. recibe los argumentos;
2. prepara una petición MCP;
3. envía la petición al controlador;
4. espera la respuesta;
5. devuelve el resultado recibido.

No ejecuta directamente Docker ni las pruebas.

## Implementación real del servidor MCP

La herramienta real del servidor MCP:

1. recibe la petición;
2. prepara la ejecución;
3. crea el contenedor Docker, cuando corresponde;
4. ejecuta el código y las pruebas;
5. captura el resultado;
6. devuelve la información obtenida.

---

# 4. ¿Por qué se utiliza un wrapper en Agent Smith?

El código generado por el LLM se ejecuta dentro de un **worker aislado**.

Ese worker no debe tener acceso directo a todas las capacidades del sistema. Por ejemplo, no debe ejecutar libremente operaciones externas o controlar directamente el entorno MCP.

Sin embargo, el código generado por el LLM necesita poder utilizar herramientas como `run_test()`.

El wrapper resuelve este problema:

```text
El código del LLM
    puede llamar a run_test()
```

pero:

```text
El worker
    no ejecuta directamente la herramienta real
```

En lugar de eso, el wrapper convierte la llamada en una petición estructurada.

Así se consigue separar:

```text
Código del LLM
    │
    ▼
Wrapper dentro del worker
    │
    ▼
Comunicación con sandbox.py
    │
    ▼
Cliente MCP
    │
    ▼
Servidor MCP
    │
    ▼
Ejecución real de la herramienta
```

---

# 5. Cómo se implementa el wrapper en este proyecto

En `json_worker.py`, el worker crea funciones wrapper para las herramientas MCP disponibles.

La idea simplificada es esta:

```python
def crear_wrapper(nombre_herramienta):
    def wrapper(*args, **kwargs):
        # Preparar la petición
        # Enviar mcp_request
        # Esperar mcp_result
        # Devolver el resultado
        ...

    return wrapper
```

La función exterior crea el wrapper y la función interior es la que se ejecutará cuando el código del LLM llame a la herramienta.

Por ejemplo, conceptualmente:

```text
crear_wrapper("run_test")
        │
        ▼
Devuelve una función
        │
        ▼
Esa función se guarda con el nombre run_test
```

El namespace del código ejecutado por el LLM termina teniendo algo equivalente a:

```python
run_test = wrapper_creado
```

Por eso el código generado puede escribir:

```python
resultado = run_test(solution)
```

Python busca `run_test` en el namespace y encuentra la función wrapper.

---

# 6. Qué hace el wrapper cuando se llama

Cuando el LLM genera:

```python
resultado = run_test(solution)
```

sucede lo siguiente.

## Paso 1: Python encuentra el wrapper

El nombre `run_test` apunta a la función wrapper creada por el worker.

No apunta directamente a Docker ni al servidor MCP.

```text
run_test
   │
   ▼
wrapper local
```

## Paso 2: El wrapper recibe los argumentos

El wrapper recibe la solución mediante sus argumentos:

```text
solution
```

Puede recibirlos como argumentos posicionales o como argumentos nombrados.

Después debe convertirlos al formato esperado por la herramienta MCP.

## Paso 3: El wrapper prepara un mensaje

El wrapper utiliza la información recibida para construir una petición.

El mensaje tiene esta idea:

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

Los campos significan:

* `"type": "mcp_request"`: indica que se solicita una operación MCP;
* `"operation": "call_tool"`: indica que se quiere llamar a una herramienta;
* `"name": "run_test"`: identifica la herramienta;
* `"arguments"`: contiene los argumentos de la llamada.

## Paso 4: El wrapper envía el mensaje

El mensaje se escribe en el canal de salida del worker, normalmente `stdout`.

En este proyecto, `stdout` no se utiliza únicamente para imprimir texto. También sirve como canal de comunicación entre procesos.

El mensaje viaja así:

```text
wrapper
   │
   ▼
stdout del worker
   │
   ▼
sandbox.py
```

## Paso 5: El wrapper espera la respuesta

Después de enviar `mcp_request`, el wrapper todavía no tiene el resultado de la prueba.

Por eso espera un mensaje de respuesta, normalmente identificado como:

```text
mcp_result
```

Durante ese tiempo, la llamada a:

```python
run_test(solution)
```

permanece esperando.

## Paso 6: El wrapper recibe la respuesta

Cuando `sandbox.py` termina de gestionar la petición, envía la respuesta al worker mediante su entrada estándar, `stdin`.

El wrapper recibe esa respuesta y extrae el resultado.

## Paso 7: El wrapper devuelve el valor

Finalmente, el wrapper hace que la llamada parezca una función normal:

```python
resultado = run_test(solution)
```

El valor asignado a `resultado` procede realmente de la herramienta MCP ejecutada fuera del worker.

---

# 7. El wrapper funciona como un adaptador

En este proyecto, el wrapper adapta dos mundos diferentes:

## Mundo del código del LLM

El LLM utiliza una interfaz sencilla:

```python
resultado = run_test(solution)
```

## Mundo de la comunicación entre procesos y MCP

Internamente hay que:

1. construir JSON;
2. escribir en `stdout`;
3. esperar en `stdin`;
4. interpretar mensajes;
5. comunicarse con el cliente MCP;
6. esperar al servidor MCP;
7. recibir el resultado.

El wrapper oculta esa complejidad al código del LLM.

```text
Interfaz sencilla:
    run_test(solution)

Implementación interna:
    mcp_request
    stdout
    sandbox.py
    cliente MCP
    servidor MCP
    Docker
    mcp_result
    stdin
```

---

# 8. Analogía sencilla

Imagina que el código del LLM es un cliente de una cafetería.

El cliente pide:

```text
Un café, por favor.
```

El wrapper es el camarero:

1. recibe el pedido;
2. lo traduce al formato de la cocina;
3. lleva el pedido;
4. espera;
5. recoge el café;
6. se lo entrega al cliente.

El cliente no necesita saber:

* cómo funciona la cocina;
* quién prepara el café;
* qué máquinas se utilizan;
* cuánto tarda el proceso.

En Agent Smith:

```text
Código del LLM
    = cliente

Wrapper
    = camarero

Servidor MCP
    = cocina

Docker
    = entorno donde se prepara el pedido

Resultado MCP
    = café entregado al cliente
```

La analogía no es exacta en todos los detalles, pero sirve para entender la función del wrapper.

---

# Por lo tanto...

Un **wrapper** es una función intermedia que ofrece una interfaz sencilla para utilizar una operación que puede ser más compleja internamente.

En Agent Smith:

```python
resultado = run_test(solution)
```

parece una llamada normal, pero el nombre `run_test` apunta a un wrapper dentro del worker.

El wrapper:

1. recibe `solution`;
2. construye un mensaje `mcp_request`;
3. lo envía por `stdout`;
4. espera un `mcp_result`;
5. recibe el resultado;
6. lo devuelve al código del LLM.

Después, fuera del worker:

```text
sandbox.py
    recibe la petición
    llama al cliente MCP

Servidor MCP
    ejecuta la herramienta real
    puede crear un Docker
    ejecuta las pruebas
    devuelve el resultado
```

La idea más importante es:

> **El wrapper hace que una operación externa y compleja parezca una función Python normal para el código que la utiliza.**
