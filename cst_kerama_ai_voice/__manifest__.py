{
    "name": "Khatdecor AI Voice Input",
    "summary": "Speak to the MuK AI assistant: a microphone in the chat composer "
               "that turns Uzbek, Russian or English speech into text.",
    "description": """
Khatdecor AI Voice Input
========================

Adds one button to the AI assistant's composer.  Hold a conversation with the
assistant by speaking instead of typing — useful on the shop floor and in the
warehouse, where typing Uzbek on a phone is the slow part.

The recording is made in the browser and transcribed by OpenAI using **the API
key muk_ai already has**; no second account, no second key, nothing new to
configure.

**Why `gpt-4o-transcribe` and why no language code.**  Measured on this
system with a spoken Uzbek sentence:

* ``gpt-4o-transcribe`` returned it word for word;
* ``whisper-1`` returned Armenian gibberish — it does not know Uzbek;
* passing ``language=uz`` makes the API refuse the request outright
  ("Language code 'uz' is not recognized"), so detection is left automatic and
  the language is hinted through the prompt instead.

The text lands in the composer for the person to read before sending, because
a misheard word should be corrected by the person who said it, not by the
assistant acting on it.
    """,
    "author": "Khatdecor",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["muk_ai", "base_setup"],
    "data": [
        "data/voice_defaults.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cst_kerama_ai_voice/static/src/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
