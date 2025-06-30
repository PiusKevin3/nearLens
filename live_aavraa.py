import speech_recognition as sr
import pyttsx3
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-pro")

# Initialize TTS
engine = pyttsx3.init()

def speak(text):
    engine.say(text)
    engine.runAndWait()

def listen():
    recognizer = sr.Recognizer()
    mic = sr.Microphone()
    with mic as source:
        print("🎤 Listening...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    try:
        print("🧠 Recognizing...")
        text = recognizer.recognize_google(audio)
        print(f"🗣️ You said: {text}")
        return text
    except sr.UnknownValueError:
        print("❌ Could not understand.")
        return None
    except sr.RequestError as e:
        print(f"❌ Recognition error: {e}")
        return None

def ask_gemini(prompt):
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Error: {e}"

# Main loop
if __name__ == "__main__":
    print("🤖 Aavraa-AI is ready. Say something!")

    while True:
        user_input = listen()
        if user_input:
            if user_input.lower() in ["exit", "quit", "stop"]:
                speak("Goodbye!")
                break
            ai_response = ask_gemini(user_input)
            print(f"🤖 Aavraa-AI: {ai_response}")
            speak(ai_response)
