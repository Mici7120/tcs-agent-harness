# `tcs-agent-harness`

Motor modular open-source de **Agent Harness Engineering** en Python 3.12+, diseñado sintetizando la arquitectura real de los principales repositorios de **Google** y grandes referentes de la industria:

- **Google ADK (`google/adk-python`)**: Flujo inmutable de eventos (`HarnessEvent`), persistencia de sesiones `.jsonl` y compactación automática de contexto por umbral de tokens con retención de cola (`ContextCompactor`).
- **Google Gemini CLI (`google-gemini/gemini-cli`)**: Separación estricta entre core y UI, `PolicyEngine` declarativo (`ALLOW` / `ASK` / `DENY`), `ConfirmationBus` desacoplado y decoradores de modelo (`ScriptedModelProvider`, `RecordingModelProvider`) para pruebas deterministas.
- **Pi (`earendil-works/pi`) & `SWE-agent/mini-swe-agent`**: Núcleo quirúrgico de herramientas mínimas (`read_file`, `write_file`, `edit_file`, `search_files`, `run_bash`) y ejecución sin estado por comando intercambiable entre proceso local y contenedor Docker.
- **OpenAI Codex (`openai/codex`)**: Descubrimiento jerárquico de guías `AGENTS.md` y confinamiento estricto al workspace.
- **Anthropic (`claude-code` & 3-Agent Harness Pattern)**: Carga progresiva bajo demanda de `SKILL.md` (`activate_skill`), sensores de verificación antes de finalizar (`CommandStopGate`), subagentes con contexto aislado y pipeline de 3 etapas (`Planner → Worker → Evaluator`).

---

## Arquitectura

```text
Agente Confiable = Modelo (Gemini / Claude / OpenAI / Local) + Harness (Guides + Loop + Policy + Sensors)
```

| Subsistema | Módulo | Responsabilidad |
| :--- | :--- | :--- |
| **1. Event Protocol** | `tcs_harness.events` | Stream inmutable `HarnessEvent` persistido en `.tcs/sessions/<id>/events.jsonl`. |
| **2. Model Gateway** | `tcs_harness.models` | Adaptador nativo **Google Gemini** (`google-genai`), **Anthropic**, **OpenAI / Ollama / vLLM** y mocks deterministas. |
| **3. Context & Skills** | `tcs_harness.context` | Carga automática de `AGENTS.md`, catálogo progresivo `SKILL.md` y `ContextCompactor`. |
| **4. Minimal Tools + MCP** | `tcs_harness.tools`, `mcp` | 5 herramientas base con truncado spill-to-disk + cliente **MCP JSON-RPC 2.0 stdio**. |
| **5. Policy & StopGates** | `tcs_harness.policy` | 4 modos (`read_only`, `strict_ask`, `auto_edit`, `autonomous`), `ConfirmationBus` y sensores `CommandStopGate`. |
| **6. Environments** | `tcs_harness.env` | `LocalEnvironment` (confinado al workspace) y `DockerSandboxEnvironment` (`--network none`, límites de CPU/RAM). |
| **7. Subagents & Pipeline** | `tcs_harness.subagents` | Delegación con ventana aislada (`researcher`, `planner`, `worker`, `evaluator`) y `ThreeStagePipeline`. |

---

## Instalación Rápida

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

Diagnóstico del entorno y proveedores configurados:

```bash
.venv/bin/tcs doctor
.venv/bin/tcs skills
```

---

## Uso desde CLI (`tcs`)

```bash
# 1. Ejecutar una tarea con Google Gemini y un sensor StopGate que exige que pytest pase antes de terminar
export GEMINI_API_KEY="tu-api-key"
tcs run "Agrega validación de entrada en utils.py y su test unitario" \
  --model gemini:gemini-2.5-flash \
  --verify-cmd "pytest -q"

# 2. Sesión interactiva multi-turno en terminal
tcs chat --model gemini:gemini-2.5-pro

# 3. Ejecutar comandos bash dentro de un contenedor Docker aislado (--network none)
tcs run "Analiza y corrige el script de procesamiento" --docker -y

# 4. Pipeline autónomo de 3 etapas (Planner -> Worker -> Evaluator independiente)
tcs pipeline "Implementa un módulo cache LRU con tests completos" --model gemini:gemini-2.5-flash -y

# 5. Usar modelos locales vía Ollama o compatibles con OpenAI / Anthropic
tcs run "Explica la arquitectura de este repositorio" --model ollama:qwen2.5-coder
```

---

## Uso como SDK en Python

```python
import asyncio
from pathlib import Path
from tcs_harness import (
    AgentRunner,
    ApprovalMode,
    AutoApproveBus,
    CommandStopGate,
    HarnessConfig,
    HookManager,
    PolicyEngine,
    register_subagent_tool,
)

async def main() -> None:
    cfg = HarnessConfig(
        model="gemini:gemini-2.5-flash",
        workspace=Path("."),
        max_steps=20,
    )
    runner = AgentRunner(
        config=cfg,
        policy=PolicyEngine(mode=ApprovalMode.AUTO_EDIT),
        confirmation_bus=AutoApproveBus(),
        hooks=HookManager(stop_gates=[CommandStopGate(".venv/bin/pytest -q")]),
    )
    register_subagent_tool(runner)

    result = await runner.run("Inspecciona los skills disponibles y resume la arquitectura.")
    print(result.final_output)

asyncio.run(main())
```

---

## Pruebas y Calidad

```bash
.venv/bin/pytest -v
.venv/bin/ruff check src tests
```