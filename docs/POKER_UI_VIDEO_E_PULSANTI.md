# Poker UI: video strip e pulsanti azione

## Cosa e' stato introdotto

- Generazione media strip con supporto video (quando disponibile nel media pipeline).
- Salvataggio di clip strip in `game_state.flags["poker_strip_videos"]`.
- Galleria UI con entry video e pulsante `Apri clip`.
- Anteprima tavolo che resta su immagine statica aggiornata.
- Pulsanti rapidi per azioni poker:
  - `Check`
  - `Vedo`
  - `Fold`
  - `Punta BB`
  - `Rilancio Min`
  - `All-in`
- Abilitazione/disabilitazione pulsanti in base alle azioni legali correnti.

## File toccati

- `src/luna/systems/mini_games/poker/poker_game.py`
- `src/luna/ui/poker_window.py`

## Note operative

- Se `video_available` e' disattivo, il flusso continua con la sola immagine.
- Le clip vengono aperte nel player video di sistema tramite URL locale.
- Le azioni rapide generano gli stessi comandi testuali gia' supportati dal parser poker.

