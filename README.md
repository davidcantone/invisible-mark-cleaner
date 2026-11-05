# Invisible Mark Cleaner

![Report screen](docs/screenshots/report.png)

## Español

### Qué es

Invisible Mark Cleaner es un programa de escritorio para un PDF. Busca marcas de texto que no se ven en la página, muestra un informe en la ventana y guarda una copia limpia junto al archivo original. El original no cambia.

No hay servidor, ni cuenta, ni telemetría. El programa no abre conexiones de red.

### Qué detecta

El informe puede incluir estas marcas.

- Texto blanco, o casi blanco, sobre un fondo claro.
- Texto transparente.
- Texto con modo de renderizado 3.
- Capas de contenido opcional ocultas.
- Metadatos con aspecto de marca en el diccionario Info y en XMP.

### Qué no hace

- No envía el PDF a ningún sitio.
- No pide una cuenta.
- No envía telemetría.
- No abre una conexión de red.
- No modifica el PDF original.

### Cómo usarlo

1. Abre Invisible Mark Cleaner.
2. Arrastra un PDF a la ventana, o pulsa **Choose PDF...**.
3. Lee el informe. La tabla tiene las columnas Page, Type, Text y Details. Si la marca no pertenece a una página, la columna Page dice Document.
4. La copia limpia queda en la misma carpeta. El nombre es `nombre-clean.pdf`. Si ese archivo ya existe, el nombre pasa a `nombre-clean-2.pdf`, luego `nombre-clean-3.pdf`, y así sucesivamente.

Si la carpeta no se puede escribir, el programa pide otra ruta. Si no hay marcas, el informe lo dice y la copia limpia se guarda igual.

### Privacidad

Todo el trabajo ocurre en el equipo. El programa no abre conexiones de red, no envía telemetría y no pide una cuenta.

### Descargar e instalar

El programa está pensado para macOS 12 o posterior en un Mac Intel, y para Windows 10 y Windows 11 de 64 bits.

En macOS, abre `InvisibleMarkCleaner.dmg` y copia Invisible Mark Cleaner a la carpeta Aplicaciones. La compilación no lleva un certificado Developer ID. La primera vez, haz clic derecho en la app y elige Open. Si macOS la bloquea, en macOS 12 Monterey abre Preferencias del Sistema > Seguridad y privacidad > General y pulsa «Abrir igualmente» (en macOS 13 o posterior: Ajustes del Sistema > Privacidad y seguridad).

En Windows, descarga `InvisibleMarkCleaner.exe`. Si aparece SmartScreen, elige More info y después Run anyway.

### Línea de comandos

Para un informe en la terminal.

```bash
invisible-mark-cleaner-cli ARCHIVO.pdf
invisible-mark-cleaner-cli ARCHIVO.pdf -o copia.pdf
```

El programa termina con el código 0 cuando la copia limpia está escrita. Termina con el código 2 cuando el PDF no se puede limpiar, y el mensaje queda en la salida de error.

La app congelada también puede limpiar sin abrir la ventana. Eso permite comprobar el paquete en un agente de integración, porque el ejecutable de Windows no tiene consola.

```bash
invisible-mark-cleaner --clean ARCHIVO.pdf --output copia.pdf
```

Junto a la copia limpia queda un informe JSON. Si la copia es `copia.pdf`, el informe es `copia.pdf.report.json`.

### Compilar desde el código

Hace falta Python 3.12. Las dependencias están fijadas en `pyproject.toml`. Esas versiones son las últimas que publican ruedas para macOS 12 en Intel. No las subas.

En un Mac Intel, o en el ejecutor `macos-15-intel` de GitHub, el script crea el entorno, instala el paquete, ejecuta las pruebas, construye `Invisible Mark Cleaner.app`, comprueba que los binarios piden como máximo `MACOS_MIN` y contienen x86_64, limpia un PDF de prueba y genera `dist/InvisibleMarkCleaner.dmg`.

```bash
bash scripts/build_mac.sh
```

La versión mínima de macOS sale de la variable `MACOS_MIN` (por defecto `12.0`). El script la usa como límite del comprobador de binarios y como `LSMinimumSystemVersion` del `Info.plist`, así la app nunca dice que funciona en un macOS más antiguo que sus binarios. Para conseguir el mínimo 12.0, usa el Python 3.12 del instalador oficial de python.org, que está compilado para versiones de macOS anteriores a la 12. Un Python compilado en el propio Mac (por ejemplo con pyenv) hereda la versión de ese Mac. En un MacBook con macOS 12.7.6, el Python 3.12.0 de pyenv dejó `libpython` y los `.so` de la biblioteca estándar en 12.6. En ese caso, compila con:

```bash
MACOS_MIN=12.6 bash scripts/build_mac.sh
```

Esa app funciona en macOS 12.6 o posterior. Las Mac con macOS 12.0 a 12.5 necesitan una compilación hecha con el Python de python.org.

En Windows 10 u 11 de 64 bits.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

El ejecutable queda en `dist\InvisibleMarkCleaner.exe`.

GitHub Actions hace lo mismo. El flujo corre al empujar a `main`, al crear una etiqueta `v*` y al lanzarlo a mano. Los artefactos del flujo son el `.dmg` y el `.exe`.

En Linux el mismo spec de PyInstaller produce una carpeta en `dist/invisible-mark-cleaner/`. Esa build sirve para comprobar el paquete. La app que se entrega es la de macOS y la de Windows.

### Firma y notarización

Firmar y notarizar es opcional y de pago. Hace falta una cuenta de desarrollador de Apple, o un certificado de firma de código de Windows.

En macOS, con un certificado Developer ID.

```bash
codesign --deep --force --options runtime --sign "Developer ID Application: Tu Nombre" "Invisible Mark Cleaner.app"
xcrun notarytool submit InvisibleMarkCleaner.dmg --apple-id APPLE_ID --team-id TEAM_ID --password APP_PASSWORD --wait
xcrun stapler staple "Invisible Mark Cleaner.app"
```

En Windows, con la herramienta signtool del SDK. La URL de tiempo es la de tu proveedor de certificados.

```text
signtool sign /fd SHA256 /tr TIMESTAMP_URL /td SHA256 InvisibleMarkCleaner.exe
```

### Pruebas

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Para ver la ventana en Linux sin una pantalla física.

```bash
xvfb-run -a python scripts/ui_smoke.py tests/fixtures/white_text.pdf /tmp/ui-smoke
```

El script abre la ventana, suelta el PDF por el mismo camino que un arrastre, espera el informe y guarda `idle.png` y `done.png`.

### Limitaciones conocidas

- **OCR de PDFs escaneados.** El texto OCR suele ir en modo de renderizado 3 encima de la imagen de la página. El programa lo borra, así que un escaneo limpio deja de ser buscable.
- **Texto en modo Tr 7 (solo recorte).** Se conserva. No pinta, pero recorta lo que se dibuja después, y borrarlo podría cambiar lo visible.
- **Capas solo de impresión.** Una capa apagada en pantalla pero activa al imprimir se trata como oculta y se borra.
- **Fuentes sin tabla de anchos.** Con las 14 fuentes estándar sin `/Widths`, si se borra texto oculto en medio de una línea, el resto de esa línea se desplaza. Si el texto oculto va en su propia línea, no pasa nada.
- **Fondo claro u oscuro.** Se decide con los rellenos e imágenes dibujados antes del texto. No se analizan trazados de recorte, modos de fusión ni formas dibujadas encima del texto después.
- **Transparencia por máscara suave.** Solo se leen `/ca` y `/CA`. Texto ocultado con `/SMask` o con un modo de fusión no se detecta.
- **Imágenes.** Toda imagen cuenta como fondo oscuro, así que el texto blanco encima de una imagen se conserva siempre, aunque la imagen sea clara.
- **Formularios reutilizados.** Un Form XObject se decide una vez, con el fondo de su primer uso. Si se reutiliza sobre un fondo distinto, el resultado vale para todos sus usos.
- **No se analizan.** Anotaciones y campos de formulario, patrones de mosaico, glifos Type3, texto fuera de la página y texto diminuto.
- **Metadatos.** Las claves no estándar de Info y XMP se borran siempre. Los campos estándar (Title, Subject, Keywords, Producer…) se borran solo si parecen instrucciones para un modelo o identificadores opacos. Es una heurística: puede fallar en ambos sentidos.
- **Un archivo cada vez.** Limpiar una carpeta entera queda pendiente (TODO).
- **Builds sin firmar.** El `.app` y el `.exe` no están firmados. Ver «Firma y notarización».

## English

### What it is

Invisible Mark Cleaner is a desktop program for one PDF. It looks for text marks that do not show on the page, shows a report in the window, and saves a clean copy next to the original file. The original file does not change.

There is no server, no account, and no telemetry. The program opens no network connections.

### What it detects

The report can include these marks.

- White text, or near-white text, on a light background.
- Transparent text.
- Text with render mode 3.
- Hidden optional content layers.
- Marker-like metadata in the Info dictionary and in XMP.

### What it never does

- It does not send the PDF anywhere.
- It does not ask for an account.
- It does not send telemetry.
- It does not open a network connection.
- It does not modify the original PDF.

### How to use it

1. Open Invisible Mark Cleaner.
2. Drop one PDF on the window, or click **Choose PDF...**.
3. Read the report. The table columns are Page, Type, Text, and Details. When a mark is not tied to a page, the Page column says Document.
4. The clean copy is saved in the same folder. The name is `name-clean.pdf`. When that file already exists, the name becomes `name-clean-2.pdf`, then `name-clean-3.pdf`, and so on.

When the folder cannot be written, the program asks for another path. When no marks are found, the report says so and the clean copy is saved anyway.

### Privacy

All of the work happens on the computer. The program opens no network connections, sends no telemetry, and asks for no account.

### Download and install

The program targets macOS 12 or later on an Intel Mac, and 64-bit Windows 10 and Windows 11.

On macOS, open `InvisibleMarkCleaner.dmg` and copy Invisible Mark Cleaner to the Applications folder. The build is not signed with a Developer ID certificate. The first time, right-click the app and choose Open. If macOS blocks the app, on macOS 12 Monterey open System Preferences > Security & Privacy > General and click Open Anyway (on macOS 13 or later: System Settings > Privacy & Security).

On Windows, download `InvisibleMarkCleaner.exe`. If SmartScreen appears, choose More info, then Run anyway.

### Command line

For a report in the terminal.

```bash
invisible-mark-cleaner-cli FILE.pdf
invisible-mark-cleaner-cli FILE.pdf -o copy.pdf
```

The program exits 0 when the clean copy is written. It exits 2 when the PDF cannot be cleaned, and the message goes to stderr.

The frozen app can also clean a file without opening a window. That lets a build agent check the bundle, because the Windows executable has no console.

```bash
invisible-mark-cleaner --clean FILE.pdf --output copy.pdf
```

A JSON report is written next to the clean copy. When the copy is `copy.pdf`, the report is `copy.pdf.report.json`.

### Build from source

Python 3.12 is required. The dependencies are pinned in `pyproject.toml`. Those releases are the last ones that publish wheels for macOS 12 on Intel. Leave the pins as they are.

On an Intel Mac, or on GitHub's `macos-15-intel` runner, the script creates the environment, installs the package, runs the tests, builds `Invisible Mark Cleaner.app`, checks that the bundled binaries need at most `MACOS_MIN` and contain x86_64, cleans a test PDF, and writes `dist/InvisibleMarkCleaner.dmg`.

```bash
bash scripts/build_mac.sh
```

The minimum macOS version comes from `MACOS_MIN` (default `12.0`). The script uses it as the binary checker's limit and as `LSMinimumSystemVersion` in `Info.plist`, so the app never claims to run on an older macOS than its binaries need. For a 12.0 minimum, use Python 3.12 from the official python.org installer, which is built for macOS versions older than 12. A Python compiled on the Mac itself (pyenv, for example) inherits that Mac's version. On a MacBook running macOS 12.7.6, pyenv's Python 3.12.0 left `libpython` and the standard library `.so` files at 12.6. In that case build with:

```bash
MACOS_MIN=12.6 bash scripts/build_mac.sh
```

That app runs on macOS 12.6 or later. Macs on macOS 12.0 to 12.5 need a build made with python.org's Python.

On 64-bit Windows 10 or Windows 11.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The executable is `dist\InvisibleMarkCleaner.exe`.

GitHub Actions runs the same builds. The workflow runs on a push to `main`, on a `v*` tag, and on a manual run. The workflow artifacts are the `.dmg` and the `.exe`.

On Linux the same PyInstaller spec produces a folder at `dist/invisible-mark-cleaner/`. That build is for checking the bundle. The shipped app is the macOS app and the Windows executable.

### Signing and notarization

Signing and notarization are optional and paid. You need an Apple developer account, or a Windows code-signing certificate.

On macOS, with a Developer ID certificate.

```bash
codesign --deep --force --options runtime --sign "Developer ID Application: Your Name" "Invisible Mark Cleaner.app"
xcrun notarytool submit InvisibleMarkCleaner.dmg --apple-id APPLE_ID --team-id TEAM_ID --password APP_PASSWORD --wait
xcrun stapler staple "Invisible Mark Cleaner.app"
```

On Windows, with signtool from the Windows SDK. The timestamp URL comes from your certificate vendor.

```text
signtool sign /fd SHA256 /tr TIMESTAMP_URL /td SHA256 InvisibleMarkCleaner.exe
```

### Tests

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

To open the window on Linux without a physical display.

```bash
xvfb-run -a python scripts/ui_smoke.py tests/fixtures/white_text.pdf /tmp/ui-smoke
```

The script opens the window, drops the PDF through the same path as a drag, waits for the report, and saves `idle.png` and `done.png`.

### Known limitations

- **OCR on scanned PDFs.** OCR text usually sits in render mode 3 over the page image. The cleaner removes it, so a cleaned scan is no longer searchable.
- **Tr 7 (clip-only) text.** Kept. It paints nothing, but it clips later drawing, so removing it could change what is visible.
- **Print-only layers.** A layer that is off on screen but on for printing counts as hidden and is removed.
- **Fonts without a width table.** With standard-14 fonts that lack `/Widths`, removing hidden text in the middle of a line shifts the rest of that line. Hidden text on its own line is unaffected.
- **Light or dark background.** Decided from the fills and images painted before the text. Clipping paths, blend modes and shapes painted over the text later are not considered.
- **Soft-mask transparency.** Only `/ca` and `/CA` are read. Text hidden through `/SMask` or a blend mode is not detected.
- **Images.** Every image counts as a dark background, so white text over an image is always kept, even when the image is light.
- **Reused forms.** A form XObject is decided once, against the background of its first use. If it is reused over a different background, that decision applies to every use.
- **Not inspected.** Annotations and form fields, tiling patterns, Type3 glyph procedures, off-page text and tiny text.
- **Metadata.** Non-standard Info keys and XMP namespaces are always removed. Standard fields (Title, Subject, Keywords, Producer...) are removed only when they read like instructions to a model or opaque tracking tokens. This is a heuristic and can miss or over-match.
- **One file at a time.** Folder mode is a TODO.
- **Unsigned builds.** The `.app` and `.exe` are unsigned. See "Signing and notarization".
