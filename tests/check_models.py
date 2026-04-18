# file: check_models.py
from google import genai

# --- LA TUA CHIAVE ---
api_key = "AIzaSyC_NmECWo-Z4jYgOpQ_e8JKW7yC5gHVQqo"

print(f"🔑 Chiave in uso: ...{api_key[-6:]}")
print("📡 Contatto Google per la lista modelli...")

try:
    client = genai.Client(api_key=api_key)

    print("\n--- [LIST] ELENCO MODELLI ---")

    # Itera su tutti i modelli e stampa direttamente il nome
    for m in client.models.list():
        # Proviamo a stampare il nome, o l'intero oggetto se non ha 'name'
        try:
            print(f"[OK] {m.name}")
        except:
            print(f"❓ Oggetto modello trovato: {m}")

except Exception as e:
    print(f"\n[ERR] ERRORE: {e}")