# 🎮 UI – Gestione Missioni ed Eventi (HUD Sistema)

## 🎯 Obiettivo
Uniformare la UI per rendere immediatamente chiaro al giocatore quando si trova in:

- 🎯 Una **MISSIONE (quest principale o secondaria)**
- ⚡ Un **EVENTO (dinamico o narrativo)**
- 🎭 Un **EVENTO MACRO (festival, gita, ecc.)**

---

# 🧩 Sistema attuale
Nel progetto è già presente un widget base:

```
src/luna/ui/quest_journal_widget.py
```

Questo widget funge da pannello per missioni attive e obiettivi.

---

# 🔧 Modifica proposta: HUD dinamico unificato

Il widget deve diventare un **contenitore dinamico** che cambia stato in base al tipo di contenuto attivo.

---

# 🎨 Stati UI

## 🎯 1. Stato MISSIONE
Quando è attiva una quest strutturata.

### UI
```
┌──────────────────────────┐
│ 🎯 MISSIONE ATTIVA       │
│ Lezione privata con Luna │
│ Obiettivo: vai in aula   │
│ Stato: In corso          │
└──────────────────────────┘
```

### Logica
- Trigger da `missions/`
- Sempre persistente finché non completata
- Mostra:
  - titolo missione
  - obiettivo corrente
  - stato progresso

---

## ⚡ 2. Stato EVENTO
Quando scatta un evento dinamico o random.

### UI
```
┌──────────────────────────┐
│ ⚡ EVENTO SPECIALE       │
│ Temporale improvviso     │
│ Effetto: scuola bloccata │
└──────────────────────────┘
```

### Logica
- Trigger da `events/` o sistema globale
- Durata temporanea
- Non sempre con obiettivo

---

## 🎭 3. Stato EVENTO MACRO
Eventi scolastici importanti.

### UI
```
┌──────────────────────────┐
│ 🎭 EVENTO MACRO          │
│ Festival scolastico      │
│ Tutta la scuola coinvolta│
└──────────────────────────┘
```

### Logica
- Trigger schedulati o world events
- Influenza più missioni/NPC

---

# 🔔 Notifica temporanea (consigliata)

Ogni cambio stato deve generare un popup breve:

```
⚡ NUOVO EVENTO: Temporale
🎯 NUOVA MISSIONE: Lezione privata
```

Durata: 2–4 secondi

---

# 🧠 Logica consigliata del widget

Il widget deve ricevere uno stato unificato:

```python
state = {
    "type": "mission | event | macro_event",
    "title": "string",
    "description": "string",
    "objective": "string (optional)",
    "status": "active | completed",
}
```

---

# 🔄 Regole di override

Priorità visuale:

1. ⚡ EVENTO MACRO (più importante)
2. ⚡ EVENTO
3. 🎯 MISSIONE

Se più eventi attivi → mostra quello con priorità più alta.

---

# 🎮 UX design goal

Il giocatore deve SEMPRE capire:

- “Cosa sta succedendo?”
- “È una missione o un evento?”
- “Devo agire o è narrativa?”

---

# 🚀 Risultato finale

Con queste modifiche la UI diventa:

- più chiara
- più cinematica
- più leggibile
- più immersiva

---

# 📌 File interessato

```
src/luna/ui/quest_journal_widget.py
```

→ da trasformare in HUD dinamico missione/evento

