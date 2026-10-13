from odoo import fields, models

PARAM_MODEL = "cst_kerama_ai_voice.model"
PARAM_PROMPT = "cst_kerama_ai_voice.prompt"

# Chosen by measurement, not by reputation: whisper-1 transcribed a spoken
# Uzbek sentence as Armenian, while gpt-4o-transcribe returned it word for word.
DEFAULT_MODEL = "gpt-4o-transcribe"
DEFAULT_PROMPT = (
    "Nutq o'zbek, rus yoki ingliz tilida bo'lishi mumkin. "
    "Odoo ERP, savdo, ombor, ish haqi va buxgalteriya atamalari uchraydi."
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    cst_ai_voice_model = fields.Selection(
        [
            ("gpt-4o-transcribe", "gpt-4o-transcribe (aniqroq)"),
            ("gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe (arzonroq)"),
        ],
        string="Ovozni matnga o'girish modeli",
        config_parameter=PARAM_MODEL, default=DEFAULT_MODEL)
    cst_ai_voice_prompt = fields.Char(
        string="Tanish uchun izoh",
        config_parameter=PARAM_PROMPT, default=DEFAULT_PROMPT,
        help="Моделга кайси тил ва кандай атамалар кутилаётганини айтади.  "
             "Тил кодини бериб булмайди — OpenAI 'uz' ни кабул килмайди, "
             "шунинг учун тил айнан шу изох оркали билдирилади.")
