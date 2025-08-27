#! /Users/sadanandupase/PycharmProjects/whatsappAgent/.venv/bin/python
from fastapi import FastAPI, Request
import sys
import os
current_directory = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, current_directory)
import requests, redis, json
from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
from progress_manager import *
import persistence_manager
app = FastAPI()
persistence_manager.setup()

# r = redis.Redis(host='localhost', port=6379, decode_responses=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "llama3.2"

# def get_user_history(user_id):
#     history = r.get(user_id)
#     return json.loads(history) if history else []
#     #return []
# 
# def save_user_history(user_id, history):
#     r.set(user_id, json.dumps(history), ex=3600)  # expire after 1 hr inactivity
#     print("Saved")

MAX_LEN = 1500   # keep below 1600 to be safe

def split_message(text, max_len=MAX_LEN):
    """Split text respecting <BREAK> tags first, then word boundaries."""
    # First split on LLM-provided <BREAK>
    parts = [p.strip() for p in text.split("<BREAK>") if p.strip()]
    final_parts = []
    for part in parts:
        while len(part) > max_len:
            split_at = part.rfind(" ", 0, max_len)
            if split_at == -1:
                split_at = max_len
            final_parts.append(part[:split_at])
            part = part[split_at:].lstrip()
        final_parts.append(part)
    return final_parts

def flush_and_reset(buffer, twilio_response):
    """Send the current buffer to Twilio and reset it"""
    if buffer.strip():
        twilio_response.message(buffer.strip())
    return ""

@app.post("/whatsapp")
async def whatsapp_webhook(From: str = Form(...), Body: str = Form(...)):
    user_id = From      # WhatsApp user number
    user_message = Body

    # Load conversation history
    history = get_user_history(user_id)

    # Add user message
    history.append({"role": "user", "content": user_message})

    # Build prompt (basic example, you can format better)
    conversation_text = "\n".join([f"{h['role']}: {h['content']}" for h in history])
    with open(os.path.join(current_directory, "system_prompt.txt"), "r") as f:
        system_prompt = f.read()

    messages = [
            {"role": "system", "content": system_prompt},
        ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {"model": MODEL_NAME, "prompt": conversation_text}
    payload = {
        "model": "llama3.2",  # or llama3, phi3, etc.
        "messages": messages,
        "stream": True
    }

    twilio_response = MessagingResponse()
    print("Sending payload")
    buffer = ""
    with requests.post(OLLAMA_URL, json=payload, stream=True) as response:
        if response.status_code != 200:
            print("Error from Ollama:", response.text)
            twilio_response = MessagingResponse()
            twilio_response.message("⚠️ LLM error, please try again later.")
            return Response(content=str(twilio_response), media_type="application/xml")

        llm_reply = ""
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode("utf-8"))
                    if "message" in data and "content" in data["message"]:
                        buffer += data["message"]["content"]

                    # Handle <BREAK> tags suggested by LLM
                    while "<BREAK>" in buffer:
                        part, buffer = buffer.split("<BREAK>", 1)
                        buffer = buffer.lstrip()
                        buffer = flush_and_reset(part, twilio_response)

                    # Handle length overflow (safety check)
                    if len(buffer) >= MAX_LEN:
                        buffer = flush_and_reset(buffer, twilio_response)

                    if data.get("done", False):
                        # Flush whatever is left
                        buffer = flush_and_reset(buffer, twilio_response)

                except Exception as e:
                    print("Streaming parse error:", e)


    print(f"Final LLM reply: {llm_reply}")
    event = {
        "type": "history_saved",
        "user_id": user_id,
        "message": llm_reply
    }
    r.publish("events", json.dumps(event))
    # Add bot reply to history
    history.append({"role": "assistant", "content": llm_reply})
    save_user_history(user_id, history)

    # # Reply to WhatsApp
    # 
    # 
    # chunks = split_message(llm_reply)
    # for chunk in chunks:
    #     twilio_response.message(chunk)

    # twilio_response.message(llm_reply)
    return Response(content=str(twilio_response), media_type="application/xml")


@app.post("/hook")
async def chat(From: str = Form(...), Body: str = Form(...)):
   response = MessagingResponse() 
   msg = response.message(f"Hi {From}, you said: {Body}")
   return Response(content=str(response), media_type="application/xml")
