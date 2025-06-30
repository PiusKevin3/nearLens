from fastapi import FastAPI
from wake_assistant import run_wake_loop

app = FastAPI()

@app.get("/trigger/")
def trigger_listen():
    result = run_wake_loop()
    return result
