# Luna RPG v8 — Setup

## Prima installazione

```bat
cd D:\luna-rpg-v8
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

## Configurare le API keys

Apri `.env` e inserisci le tue chiavi:
```
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
```

## Avviare il gioco

```bat
run_game.bat           ← avvio normale
run_game_debug.bat     ← debug, senza media
run_game.bat --no-media ← no immagini, più veloce
```

## Stato sviluppo

Tutte le milestone e i bug tracciati in: `docs/V8_PROGRESS.md`
Spec completa in: `docs/LUNA_V8_SPEC.md`
