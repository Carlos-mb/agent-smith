## Qué es el `namespace`

Es un simple **diccionario de Python** (`dict[str, Any]`) que hace de "mundo" en el que vive el código del LLM. En Python, cuando ejecutas código con `exec(code, globals, locals)`, ese `globals`/`locals` **es** literalmente el espacio de nombres: dónde busca variables, dónde busca funciones, dónde busca hasta los propios `builtins` (`print`, `len`, `import`...). Si algo no está en ese diccionario (ni es un builtin normal de Python), simplemente no existe para ese código — obtendrías un `NameError`.

Aquí `namespace` se usa como **ambos a la vez** (`globals` y `locals`):

```python
exec(compile(code, "<sandbox>", "exec"), namespace, namespace)
```

## Para qué lo usamos: dos razones

**1. Persistencia entre iteraciones.** Es la respuesta a tu pregunta de antes sobre por qué `solution` sobrevive de la iteración 1 a la 2 — porque es el **mismo diccionario** el que se reutiliza en cada llamada a `execute_block`, nunca se recrea. Cuando el LLM escribe `solution = "..."`, eso literalmente añade la clave `"solution"` a este diccionario; en la siguiente iteración, sigue ahí.

**2. Es el único "menú" de lo que el LLM puede usar.** Como se construye a mano (no es el `namespace` normal de Python, con todo disponible), tú decides exactamente qué entra:

```python
namespace = {
    "__builtins__": safe, "__name__": "__sandbox__",
    "final_answer": final_answer, "mcp_call_tool": mcp_call_tool,
    "read_resource": read_resource, "get_prompt": get_prompt,
}
for tool in tools:
    ...
    namespace[name] = _make_tool_wrapper(tool, input_stream, output_stream)
```

Es decir: `namespace` no es solo "memoria" — es también la **superficie de API completa** que el LLM tiene disponible. Ves aquí mismo confirmado lo de la sección anterior: `final_answer` está codificado a mano (siempre presente), y las herramientas MCP (`run_tests`, o las 9 de SWE-bench el día que estén) se añaden en el bucle, una por cada `tool` descubierta — el wrapper dinámico que ya explicamos.

## Dónde se limita, con dos capas de restricción muy distintas

**a) Los `builtins` — lo primero que se mete en el `namespace`:**

```python
safe = _make_safe_builtins(config)
namespace = {"__builtins__": safe, ...}
```

`safe` es el diccionario de funciones básicas permitidas (`print`, `len`, `str`, `int`...) más el `__import__` restringido que ya vimos (`safe["__import__"] = _make_safe_import(...)`) y el `open` restringido a rutas permitidas (`safe["open"] = _make_safe_open(...)`). Esto limita **qué operaciones básicas del lenguaje** están disponibles.

**b) El filtro de nombres de herramientas, dentro del propio bucle:**

```python
if (name.isidentifier() and not keyword.iskeyword(name)
        and name not in safe and name not in namespace):
    namespace[name] = _make_tool_wrapper(tool, input_stream, output_stream)
else:
    logger.debug("Herramienta %s disponible mediante mcp_call_tool; nombre reservado o no válido", name)
```

Esto es un límite distinto, más sutil: antes de añadir el wrapper de una herramienta con el nombre que anuncie el servidor MCP, comprueba que ese nombre:
- sea un identificador Python válido (`name.isidentifier()`),
- no sea una palabra reservada (`not keyword.iskeyword(name)`, para que no puedas registrar una herramienta literalmente llamada `class` o `def`),
- y no choque con algo que ya exista en `safe` o en el propio `namespace` (para que un servidor MCP malicioso o mal hecho no pueda, por ejemplo, anunciar una herramienta llamada `"print"` o `"final_answer"` y **sobrescribir** silenciosamente una función crítica).

Si el nombre no pasa esas comprobaciones, la herramienta sigue estando disponible, pero solo de forma indirecta, vía `mcp_call_tool(name, arguments)` — una función genérica que sí está siempre en el `namespace` y que no depende de que el nombre sea "seguro" como identificador Python.

## Resumen

> "`namespace` es el diccionario que hace de memoria y de API completa para el código del LLM: lo que no está ahí, no existe para él. Se limita en dos sitios: en los `builtins` que se le insertan (imports y `open` restringidos), y en el propio bucle que registra las herramientas MCP, que filtra nombres inválidos o que pudieran chocar con funciones ya reservadas como `final_answer`."