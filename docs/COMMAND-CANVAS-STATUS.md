# MyPeople Command Canvas — Estado y handoff

Fecha: 2026-08-02  
Rama: `codex/graph-command-canvas`  
Base: `main` en `18996bc`  
Remoto: `https://github.com/LordCripto-Hub/Project-Factory.git`

## Resumen ejecutivo

El Command Canvas está implementado como una evolución de `/terminal-graph` dentro del modelo actual de MyPeople. No introduce usuarios externos, agentes externos, rooms, chat, presencia, una base de datos de grafos ni un runtime paralelo.

Estado actual: **listo para revisión e integración controlada; no declarado todavía como release de producción**.

La implementación mantiene las fuentes de verdad existentes:

- roster y estado de agentes de MyPeople;
- board/tareas, comentarios, proofs y TaskSpec;
- terminales y rutas same-origin existentes;
- preferencias locales del navegador únicamente para cámara, capas y posiciones.

## Qué se construyó

### Proyección semántica

`bin/todo-server.py` enriquece la respuesta del grafo sin romper los campos existentes:

- roles derivados: `boss`, `nightwatch`, `worker`;
- telemetría de agente: `summary`, `backend`, `status`;
- edges tipados: `ASSIGNS` y `OBSERVES`;
- categorías visuales de tarea: `PRIORITY`, `EVIDENCE`, `REVIEW`, `BLOCKED`, `DELIVERED`;
- `proof_count`, `evidence_policy`, `done_condition` y `project_slug`.

### Canvas

`bin/terminal-graph.html` ahora contiene:

- rail superior con vistas `Graph`, `Mission`, `Fleet`, `Attention` y `Execution`;
- jerarquía visual Boss → Nightwatch → workers → tareas/evidencia;
- conectores SVG con tipo semántico;
- inspector de agente/tarea;
- filtros `Agents`, `Tasks`, `Evidence`, `Decisions` y `Terminals`;
- minimapa;
- cámara y layout local persistentes;
- creación y edición de tareas mediante las rutas canónicas existentes;
- previews de terminal conservando los enlaces y wrappers anteriores.

`bin/graph-canvas.css` concentra el tratamiento visual del canvas y reutiliza los tokens de `bin/mypeople-ui.css`.

## Evidencia verificada

Ejecutado en el worktree aislado:

```text
python -m unittest verify.test_graph_projection verify.test_graph_command_canvas verify.test_priorities_terminal_popup verify.test_scorpion_theme -v
Ran 13 tests ... OK

node --check verify/test_terminal_views.js
node verify/test_terminal_views.js
Wall stable: 468x318x453.5999755859375x272.1600036621094
Graph stable: 267.357421875x249.4859619140625x262.49639892578125x157.497802734375

git diff --check
clean
```

También se verificó que el script embebido del grafo parsea correctamente y que la inspección visual contiene Boss, Nightwatch, worker, tarea, inspector, capas, minimapa y toolbar.

## Límites conocidos

1. El verificador aislado completo depende de Docker y todavía no se ejecutó en esta máquina porque Docker Desktop no estaba disponible.
2. No se validó todavía un ciclo live de migración, backup, restore y rollback del contenedor.
3. El botón `Connect` es una interacción visual de selección; no persiste relaciones nuevas porque MyPeople no tiene una mutación canónica de edges.
4. Cámara, capas y posiciones son preferencias locales y no forman parte del estado operativo.
5. La prueba de navegador protege contratos y geometría estable, pero falta una matriz larga con 0, 1 y muchos workers bajo polling continuo.
6. El canvas no contiene conceptos de colaboración multiusuario ni agentes externos por decisión de alcance.

## Handoff para el agente supervisor de `main`

### Estado de Git

Commits de esta rama:

- `21aece7 feat: build mypeople command canvas`
- `ca17b46 chore: clean canvas docs whitespace`

El worktree está limpio. `main` no fue modificado.

### Orden recomendado de integración

1. Revisar este documento, `docs/superpowers/specs/2026-08-02-mypeople-graph-command-canvas-design.md` y `docs/superpowers/plans/2026-08-02-mypeople-graph-command-canvas.md`.
2. Ejecutar los tests focalizados y el test Node desde el worktree.
3. Levantar una instancia de verificación aislada con una imagen revisada; no probar contra el contenedor live.
4. Revisar manualmente `/terminal-graph` en estados de cero, uno y varios workers.
5. Verificar que el modal de tarea, comentarios, proofs, estado y terminales siguen usando las rutas existentes.
6. Crear PR desde `codex/graph-command-canvas` hacia `main`.
7. Hacer merge solo después de la revisión del agente supervisor y de la suite aislada.

### Comandos sugeridos

```bash
python -m unittest verify.test_graph_projection verify.test_graph_command_canvas verify.test_priorities_terminal_popup verify.test_scorpion_theme -v
node --check verify/test_terminal_views.js
node verify/test_terminal_views.js
git diff --check
```

Para la validación completa, seguir el flujo documentado en `verify/Invoke-IsolatedVerify.ps1` o `verify/verify.sh` con una imagen local revisada. No ejecutar `docker compose down -v` ni apuntar el verificador al estado live.

## Criterio de aceptación para integrar

El agente supervisor puede integrar cuando se cumplan estas condiciones:

- los tests focalizados y la suite aislada pasan;
- no aparecen errores de consola ni regresiones en Wall, Priorities, Dashboard o Terminal;
- los terminales mantienen su geometría durante polling;
- la tarea seleccionada muestra owner, estado, done condition, proyecto y proofs;
- las capas solo filtran la proyección y no mutan board/roster;
- no se introduce un segundo store de grafo ni conceptos de Colmeia;
- la revisión visual confirma legibilidad con 0, 1 y muchos workers.

## Decisión de release

El Command Canvas puede entrar en una **alpha privada** después de la verificación aislada y el PR. No debe presentarse todavía como una capacidad multiusuario ni como un producto Colmeia independiente: es una superficie visual avanzada sobre el runtime local de MyPeople.
