import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class PresetManager:
    DEFAULT_PRESETS = {
        "code_analyze": {
            "name": "Code Analyze",
            "temperature": 0.2,
            "max_tokens": 8000,
            "system_prompt": """Eres un asistente de analisis de codigo.
FORMATO DE ANALISIS:
- Issues: [problemas especificos encontrados]
- Security: [vulnerabilidades, si aplica]
- Performance: [oportunidades de optimizacion]
- Fix: [soluciones concretas con ejemplos de codigo]

Empieza directo con hallazgos. Sin preambulo. Si la entrada no es codigo, di: "Input is not code. Please provide code to analyze."
"""
        },
        "brainstorm": {
            "name": "Brainstorm",
            "temperature": 0.9,
            "max_tokens": 4096,
            "system_prompt": """Eres un asistente de ideacion creativa enfocado en pensamiento divergente.

Genera ideas diversas e inesperadas, desde lo practico hasta lo experimental.
- Mezcla enfoques convencionales y no convencionales
- Conecta conceptos no relacionados para activar innovacion
- Considera multiples perspectivas y contextos
- Incluye soluciones inmediatas y posibilidades de largo plazo
- Cuestiona supuestos sin caer en lo absurdo por ser absurdo

Estructura las ideas con claridad, pero permite libertad creativa en la presentacion. Prioriza cantidad y variedad sobre filtrar demasiado pronto.
"""
        },
        "reason": {
            "name": "Reason",
            "temperature": 0.3,
            "max_tokens": 6000,
            "system_prompt": """Eres un asistente de razonamiento sistematico.

Estructura todas las respuestas con progresion logica clara:
1. Identifica los componentes clave de la pregunta
2. Expone principios o hechos relevantes
3. Construye el argumento paso a paso
4. Atiende posibles contraargumentos
5. Cierra con una respuesta justificada

Usa lenguaje preciso. Muestra relaciones causales de forma explicita. Cuantifica la incertidumbre cuando corresponda.
"""
        },
        "custom": {
            "name": "Custom",
            "temperature": 1.0,
            "max_tokens": 0,
            "system_prompt": "",
            "inject_prefix": "",
            "inject_suffix": "",
            "enabled": False,
        }
    }
    
    def __init__(self, data_dir: str):
        self.presets_file = os.path.join(data_dir, "presets.json")
        self.presets = self.load()
    
    def load(self) -> Dict[str, Any]:
        """Load presets from file, creating defaults if needed"""
        if not os.path.exists(self.presets_file):
            self.save(self.DEFAULT_PRESETS)
            return self.DEFAULT_PRESETS.copy()
        
        try:
            with open(self.presets_file, 'r', encoding="utf-8") as f:
                presets = json.load(f)
            if not isinstance(presets, dict):
                logger.error("Error loading presets: expected an object")
                return self.DEFAULT_PRESETS.copy()
            custom = presets.get("custom") if isinstance(presets, dict) else None
            if isinstance(custom, dict) and "enabled" not in custom:
                legacy_prompt = "You are a helpful, balanced assistant. Match your response style to the user's needs."
                if (
                    custom.get("name") == "Custom"
                    and not custom.get("character_name")
                    and custom.get("system_prompt") == legacy_prompt
                ):
                    custom["enabled"] = False
                    custom["system_prompt"] = ""
                    custom["temperature"] = 1.0
                    custom["max_tokens"] = 0
                    custom.setdefault("inject_prefix", "")
                    custom.setdefault("inject_suffix", "")
                    self.save(presets)
            # Heal a forward-incompatible file the same way the legacy `custom`
            # migration above does: fill in any built-in presets an older or
            # partial presets.json is missing, so they reach existing installs
            # (a missing built-in is otherwise silently absent from the picker
            # served by GET /api/presets). There is no delete path for the
            # built-in keys, so this never clobbers an intentional removal.
            # Defaults first, loaded values win — user edits are preserved.
            if isinstance(presets, dict) and any(
                k not in presets for k in self.DEFAULT_PRESETS
            ):
                presets = {**self.DEFAULT_PRESETS, **presets}
                self.save(presets)
            return presets
        except Exception as e:
            logger.error(f"Error loading presets: {e}")
            return self.DEFAULT_PRESETS.copy()
    
    def save(self, presets: Dict[str, Any]) -> bool:
        """Save presets to file"""
        try:
            from core.atomic_io import atomic_write_json
            atomic_write_json(self.presets_file, presets, indent=2)
            self.presets = presets
            return True
        except Exception as e:
            logger.error(f"Error saving presets: {e}")
            return False
    
    def get(self, preset_id: str) -> Dict[str, Any]:
        """Get a specific preset"""
        return self.presets.get(preset_id)
    
    def update_custom(
        self,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
        name: str = "",
        enabled: bool = True,
        inject_prefix: str = "",
        inject_suffix: str = "",
    ) -> bool:
        """Update the custom preset"""
        self.presets["custom"] = {
            "name": name or "Custom",
            "character_name": name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "inject_prefix": inject_prefix,
            "inject_suffix": inject_suffix,
            "enabled": enabled,
        }
        return self.save(self.presets)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all presets"""
        return self.presets.copy()

    def get_user_templates(self) -> list:
        """Get user-saved character templates."""
        return self.presets.get("user_templates", [])

    def save_user_template(self, template: dict) -> bool:
        """Save a new user template or update existing by id."""
        templates = self.presets.get("user_templates", [])
        # Update existing if same id
        existing = next((i for i, t in enumerate(templates) if t.get("id") == template.get("id")), None)
        if existing is not None:
            templates[existing] = template
        else:
            templates.append(template)
        self.presets["user_templates"] = templates
        return self.save(self.presets)

    def delete_user_template(self, template_id: str) -> bool:
        """Delete a user template by id."""
        templates = self.presets.get("user_templates", [])
        self.presets["user_templates"] = [t for t in templates if t.get("id") != template_id]
        return self.save(self.presets)

    def get_group_presets(self) -> list:
        """Get saved group chat presets."""
        return self.presets.get("group_presets", [])

    def save_group_presets(self, groups: list) -> bool:
        """Save group chat presets."""
        self.presets["group_presets"] = groups
        return self.save(self.presets)
