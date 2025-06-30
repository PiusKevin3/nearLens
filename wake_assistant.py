import pvporcupine
import pyaudio
import struct
import speech_recognition as sr
import pyttsx3
import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-pro")

recognizer = sr.Recognizer()
mic = sr.Microphone()
engine = pyttsx3.init()

def speak(text):
    print(f"🤖 Aavraa-AI: {text}")
    engine.say(text)
    engine.runAndWait()

def ask_gemini(question):
    response = model.generate_content(question)
    return response.text.strip()

def listen_and_respond():
    with mic as source:
        print("🎤 Listening after wake word...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    try:
        text = recognizer.recognize_google(audio)
        print(f"🗣️ You: {text}")
        response = ask_gemini(text)
        speak(response)
        return {"question": text, "response": response}
    except Exception as e:
        print("❌ Error:", str(e))
        return {"error": str(e)}

def run_wake_loop():
    porcupine = pvporcupine.create(keywords=["jarvis"])  # You can customize keyword
    pa = pyaudio.PyAudio()
    stream = pa.open(rate=porcupine.sample_rate,
                     channels=1,
                     format=pyaudio.paInt16,
                     input=True,
                     frames_per_buffer=porcupine.frame_length)

    print("🟢 Waiting for wake word: 'Hey Aavraa' (using Jarvis keyword)")
    try:
        while True:
            pcm = stream.read(porcupine.frame_length)
            pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)

            if porcupine.process(pcm_unpacked) >= 0:
                print("✅ Wake word detected!")
                return listen_and_respond()
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
        porcupine.delete()
