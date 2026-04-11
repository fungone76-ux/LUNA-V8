import asyncio
from luna.core.engine import GameEngine

async def main():
    print("--- Inizializzazione Luna RPG Engine ---")
    
    # Sostituisci "default_world" e "Luna" con gli ID reali del tuo mondo e companion
    world_id = "default_world" 
    companion = "Luna"
    
    # Inizializza l'engine (disabilitiamo i media per una chat testuale veloce)
    engine = GameEngine(world_id=world_id, companion=companion, no_media=True)
    
    try:
        await engine.initialize()
        print(f"Motore avviato. Mondo: {world_id}, Companion: {companion}")
        
        # Genera l'introduzione opzionale
        intro_result = await engine.generate_intro()
        if intro_result and intro_result.text:
            print(f"\nGioco: {intro_result.text}\n")
            
    except Exception as e:
        print(f"Errore durante l'inizializzazione: {e}")
        return

    print("--- Chat Iniziata (Digita 'fine' per chiudere) ---")

    while True:
        messaggio = input("Tu: ")
        if messaggio.lower() in ["fine", "exit", "stop"]:
            break

        if not messaggio.strip():
            continue

        # Passa l'input all'engine che lo delegherà al TurnOrchestrator
        try:
            result = await engine.process_turn(messaggio)
            print(f"\nGioco: {result.text}\n")
        except Exception as e:
            print(f"\n[Errore durante il turno]: {e}\n")

    # Chiusura pulita
    print("Salvataggio e chiusura in corso...")
    await engine.shutdown()
    print("Chiusura completata.")

if __name__ == "__main__":
    asyncio.run(main())
