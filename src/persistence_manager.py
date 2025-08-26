import sqlite3

def setup():
    sqlite_conn = sqlite3.connect("mentor.db", check_same_thread=False)
    cursor = sqlite_conn.cursor()
    
    # Create tables if not exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        name TEXT,
        topics TEXT,
        preferences TEXT,
        last_active TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_concepts (
        user_id TEXT,
        concept TEXT,
        level INTEGER,
        explanations_given INTEGER,
        examples_given INTEGER,
        assignments_given INTEGER,
        assignments_completed INTEGER,
        next_review_date TEXT,
        last_interaction TEXT,
        status TEXT,
        PRIMARY KEY (user_id, concept)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS assignments (
        user_id TEXT,
        concept TEXT,
        assignment_id TEXT,
        question TEXT,
        answer TEXT,
        feedback TEXT,
        given_at TEXT,
        status TEXT,
        PRIMARY KEY (user_id, concept, assignment_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversation_history (
        user_id TEXT,
        timestamp TEXT,
        role TEXT,
        content TEXT
    )
    """)
    
    sqlite_conn.commit()

if __name__ == "__main__":
    setup()