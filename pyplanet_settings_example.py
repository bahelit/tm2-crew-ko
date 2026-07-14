# PyPlanet settings for the Knockout / Bowl of the Night server.
#
# PyPlanet keeps its settings as plain Python modules under `settings/`. The two
# files below are the only ones you need to touch for this app. Copy the relevant
# blocks into your own `settings/base.py` and `settings/apps.py`.
#
# Everything else the app exposes (BOTN cutoff time, HUD toggles, score modes, ...)
# is a *live* setting changed in-game with `//settings` — it is NOT set here. The
# one app option that lives in this file is KNOCKOUT_STARTUP_MODE (see below).


# ─────────────────────────────────────────────────────────────────────────────
# settings/base.py  — connection + boot mode
# ─────────────────────────────────────────────────────────────────────────────

# Logins that always get every permission.
OWNERS = {
    'default': ['your_login'],
}

# How PyPlanet reaches the dedicated server. PORT here is the dedicated server's
# XML-RPC port (the <xmlrpc_port> in UserData/Config/*.xml — usually 5000), NOT
# the game's <server_port> (2350). USER/PASSWORD must match the dedicated's
# SuperAdmin authorization level.
DEDICATED = {
    'default': {
        'HOST': '127.0.0.1',
        'PORT': '5000',
        'USER': 'SuperAdmin',
        'PASSWORD': 'your_superadmin_password',
    }
}

DATABASES = {
    'default': {
        'ENGINE': 'peewee_async.MySQLDatabase',
        'NAME': 'pyplanet',
        'OPTIONS': {
            'host': 'localhost',
            'user': 'pyplanet',
            'password': 'your_db_password',
            'charset': 'utf8mb4',
        }
    }
}

# Knockout app: pin what the server boots into so it just launches and plays.
#   'knockout' = idle in TimeAttack until an admin runs //cup on
#   'botn'     = auto-start a Bowl of the Night (TimeAttack practice -> knockout)
#   'none'     = leave the server's own configured mode alone (default)
# This file key overrides the live `startup_mode` setting (//settings). Omit it
# to drive the boot mode from //settings instead.
KNOCKOUT_STARTUP_MODE = 'botn'

# Optional. Cup presets (friday / weekly / quick) already ship inside
# apps/knockout/presets.json and load automatically when this is unset.
# Point here only to override with a custom JSON file.
# KNOCKOUT_CUP_PRESETS_PATH = '/path/to/custom_presets.json'


# ─────────────────────────────────────────────────────────────────────────────
# settings/apps.py  — which apps load
# ─────────────────────────────────────────────────────────────────────────────

APPS = {
    'default': [
        # ... the contrib apps you already run (admin, jukebox, karma,
        #     local_records, live_rankings, ...) ...
        'apps.knockout',  # <-- the Knockout / BOTN app
    ]
}
