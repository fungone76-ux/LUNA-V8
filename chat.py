from google import genai

# Configura il client con la tua chiave
client = genai.Client(api_key="AIzaSyC_NmECWo-Z4jYgOpQ_e8JKW7yC5gHVQqo") # Metti la tua chiave qui

print("--- Gemini CLI Chat (Digita 'fine' per chiudere) ---")

while True:
    messaggio = input("Tu: ")
    if messaggio.lower() in ["fine", "exit", "stop"]:
        break

    # Generazione della risposta
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=messaggio
    )

    print(f"\nGemini: {response.text}\n")