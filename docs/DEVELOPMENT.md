# Desarrollo

## Preparar el entorno

```fish
cd ~/Documentos/TexasCalculadora
uv venv .venv --python 3.14          # o: python -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest
./scripts/build-helper.sh            # compila native/tcm-link/tcm-link
```

## Ejecutar

```fish
./scripts/run.sh                     # abre la aplicación
./scripts/run.sh documento.tns       # abre un documento en el editor
```

Para probar sin calculadora: *Configuración → Modo demostración*.

## Pruebas

```fish
env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
env TCM_SAMPLES=/ruta/con/tns/reales QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -k real
```

- `tests/test_tns.py`: contenedor, cifrado, Lua, reconstrucción, validación, extracción. Incluye una
  comparación byte a byte con la salida de Luna 2.1 (`tests/fixtures/hello_luna.tns`).
- `tests/test_core.py`: cliente del helper contra un helper falso (progreso, errores, reintento tras
  una descarga), calculadora simulada, escritura atómica y ajustes.
- `tests/test_ui.py`: pruebas de humo de la GUI en modo demo (conectar, listar, enviar, descargar,
  editar y reconstruir).

Los documentos reales de la calculadora no se suben al repositorio (son del usuario). Para usarlos en
las pruebas, se pasa su carpeta con `TCM_SAMPLES`.

## Probar el helper a mano

```fish
printf '1\tprobe\n2\topen\n3\tinfo\n4\tlist\t/\n5\tquit\n' | native/tcm-link/tcm-link
```

Para ver el tráfico de paquetes: `env G_MESSAGES_DEBUG=all native/tcm-link/tcm-link` (los registros
van a stderr).

## Reglas

- No hacer operaciones destructivas en la calculadora durante las pruebas. Usar `MockLink` o una
  carpeta de pruebas propia.
- No subir archivos temporales, `.venv`, el binario `tcm-link` ni documentos personales.
