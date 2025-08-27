import json
import sqlite3
import redis
import re
from datetime import datetime, timedelta

# -------------------------------
# Redis + SQLite Initialization
# -------------------------------
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

db_con = None
def get_db_connection():
    global db_con
    if not db_con:
        db_con = sqlite3.connect("mentor.db", check_same_thread=False)
    return db_con


# -------------------------------
# Conversation History
# -------------------------------
def get_user_history(user_id):
    history = r.get(f"history:{user_id}")
    if history:
        return json.loads(history)
    else:
        # fallback from SQLite
        db_con = get_db_connection()
        cursor = db_con.cursor()
        cursor.execute("SELECT role, content, timestamp FROM conversation_history WHERE user_id=? ORDER BY timestamp", (user_id,))
        rows = cursor.fetchall()
        return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]

def save_user_history(user_id, history):
    r.set(f"history:{user_id}", json.dumps(history), ex=3600)

    # persist latest message in SQLite
    if history:
        last_msg = history[-1]
        db_con = get_db_connection()
        cursor = db_con.cursor()
        cursor.execute("""
            INSERT INTO conversation_history (user_id, timestamp, role, content)
            VALUES (?, ?, ?, ?)
        """, (user_id, datetime.utcnow().isoformat(), last_msg["role"], last_msg["content"]))
        db_con.commit()
        # event = {
        #     "type": "history_saved",
        #     "user_id": user_id,
        #     "message": last_msg
        # }
        # r.publish("events", json.dumps(event))

# -------------------------------
# User Profile
# -------------------------------
def save_user_profile(user_id, profile):
    r.set(f"user:{user_id}", json.dumps(profile))
    db_con = get_db_connection()
    cursor = db_con.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, name, topics, preferences, last_active)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        profile.get("name"),
        json.dumps(profile.get("topics", [])),
        json.dumps(profile.get("preferences", {})),
        profile.get("last_active", datetime.utcnow().isoformat())
    ))
    db_con.commit()

def get_user_profile(user_id):
    data = r.get(f"user:{user_id}")
    if data:
        return json.loads(data)
    db_con = get_db_connection()
    cursor = db_con.cursor()
    cursor.execute("SELECT name, topics, preferences, last_active FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    if row:
        return {
            "name": row[0],
            "topics": json.loads(row[1]),
            "preferences": json.loads(row[2]),
            "last_active": row[3]
        }
    return None

# -------------------------------
# Concept Progress
# -------------------------------
def save_concept_progress(user_id, concept, progress):
    r.set(f"user:{user_id}:concept:{concept}", json.dumps(progress))
    db_con = get_db_connection()
    cursor = db_con.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO user_concepts 
        (user_id, concept, level, explanations_given, examples_given, assignments_given, assignments_completed, next_review_date, last_interaction, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        concept,
        progress.get("level", 0),
        progress.get("explanations_given", 0),
        progress.get("examples_given", 0),
        progress.get("assignments_given", 0),
        progress.get("assignments_completed", 0),
        progress.get("next_review_date"),
        progress.get("last_interaction", datetime.utcnow().isoformat()),
        progress.get("status", "active")
    ))
    db_con.commit()

def get_concept_progress(user_id, concept):
    data = r.get(f"user:{user_id}:concept:{concept}")
    if data:
        return json.loads(data)
    db_con = get_db_connection()
    cursor = db_con.cursor()
    cursor.execute("""
        SELECT level, explanations_given, examples_given, assignments_given, assignments_completed, next_review_date, last_interaction, status
        FROM user_concepts WHERE user_id=? AND concept=?
    """, (user_id, concept))
    row = cursor.fetchone()
    if row:
        return {
            "level": row[0],
            "explanations_given": row[1],
            "examples_given": row[2],
            "assignments_given": row[3],
            "assignments_completed": row[4],
            "next_review_date": row[5],
            "last_interaction": row[6],
            "status": row[7]
        }
    return None

# -------------------------------
# Assignments
# -------------------------------
def save_assignment(user_id, concept, assignment):
    key = f"user:{user_id}:concept:{concept}:assignments"
    current = r.get(key)
    assignments = json.loads(current) if current else []
    assignments.append(assignment)
    r.set(key, json.dumps(assignments))
    db_con = get_db_connection()
    cursor = db_con.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO assignments (user_id, concept, assignment_id, question, answer, feedback, given_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        concept,
        assignment.get("id"),
        assignment.get("question"),
        assignment.get("answer"),
        assignment.get("feedback"),
        assignment.get("given_at"),
        assignment.get("status")
    ))
    db_con.commit()

def get_assignments(user_id, concept):
    key = f"user:{user_id}:concept:{concept}:assignments"
    data = r.get(key)
    if data:
        return json.loads(data)
    db_con = get_db_connection()
    cursor = db_con.cursor()
    cursor.execute("SELECT assignment_id, question, answer, feedback, given_at, status FROM assignments WHERE user_id=? AND concept=?", (user_id, concept))
    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "question": row[1],
            "answer": row[2],
            "feedback": row[3],
            "given_at": row[4],
            "status": row[5]
        } for row in rows
    ]


def analyse_and_update_progress(user_id, message):
    """
    Analyse the latest LLM-generated reply and update concept progress.
    message: {"role": "assistant", "content": "...<CONCEPT=caching><EXAMPLE>..."}
    """

    content = message

    # --- Parse concept tag ---
    concept_match = re.search(r"<CONCEPT=(.*?)>", content)
    concept = concept_match.group(1).strip().lower() if concept_match else "general"

    # --- Parse response type ---
    response_type = None
    if "<EXPLANATION>" in content:
        response_type = "explanation"
    elif "<EXAMPLE>" in content:
        response_type = "example"
    elif "<ASSIGNMENT>" in content:
        response_type = "assignment_given"

    # --- Load current progress ---
    progress = get_concept_progress(user_id, concept) or {
        "level": 0,
        "explanations_given": 0,
        "examples_given": 0,
        "assignments_given": 0,
        "assignments_completed": 0,
        "next_review_date": None,
        "last_interaction": None,
        "status": "active"
    }

    # --- Increment counters ---
    if response_type == "explanation":
        progress["explanations_given"] += 1
    elif response_type == "example":
        progress["examples_given"] += 1
    elif response_type == "assignment_given":
        progress["assignments_given"] += 1

    # --- Update last interaction ---
    now = datetime.utcnow().isoformat()
    progress["last_interaction"] = now

    # --- Spaced repetition logic (naive version) ---
    base_days = [1, 3, 7, 14]
    review_stage = min(progress["level"], len(base_days) - 1)
    next_review = datetime.utcnow() + timedelta(days=base_days[review_stage])
    progress["next_review_date"] = next_review.date().isoformat()

    # --- Level advancement rule ---
    if progress["explanations_given"] >= 3 and progress["examples_given"] >= 2:
        progress["level"] = min(progress["level"] + 1, 2)  # cap at 2 (advanced)

    # --- Save back ---
    save_concept_progress(user_id, concept, progress)

    return progress
