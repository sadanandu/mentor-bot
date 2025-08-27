import sys
import os
current_directory = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, current_directory)
from progress_manager import *
import redis

r = redis.Redis(host='localhost', port=6379, decode_responses=True)
pubsub = r.pubsub()
pubsub.subscribe("events")

print("Worker listening for events...")
system_prompt = '''

'''

for message in pubsub.listen():
    if message["type"] == "message":
        event = json.loads(message["data"])
        if event["type"] == "history_saved":
            user_id = event["user_id"]
            msg = event["message"]
            analyse_and_update_progress(user_id, msg)


