from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pymysql, os
from .ladder import elo_update

scheduler = BackgroundScheduler()

def simulate_match(bot_a_id, bot_b_id, game):
    """
    Call your game engine / sandbox runner here.
    Return tuple (score_a, score_b, details). Example: (1,0,"A won")
    """
    # ... implement actual simulation or HTTP call to engine ...
    raise NotImplementedError

def run_scheduled_matches():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'), user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'), database=os.getenv('DB_NAME'),
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches WHERE status='scheduled' AND scheduled_at <= NOW() LIMIT 5")
            matches = cursor.fetchall()
            for m in matches:
                try:
                    cursor.execute("UPDATE matches SET status='running', run_at = NOW() WHERE id=%s", (m['id'],))
                    conn.commit()
                    score_a, score_b, details = simulate_match(m['bot_a'], m['bot_b'], m['game'])
                    winner = None
                    if score_a > score_b: winner = m['bot_a']
                    elif score_b > score_a: winner = m['bot_b']
                    cursor.execute("""
                        INSERT INTO match_results (match_id, winner, score_a, score_b, details)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (m['id'], winner, score_a, score_b, details))
                    # load current ratings
                    cursor.execute("SELECT id, rating FROM bots WHERE id IN (%s,%s)", (m['bot_a'], m['bot_b']))
                    rows = {r['id']: r['rating'] for r in cursor.fetchall()}
                    r_a = rows.get(m['bot_a'], 1500)
                    r_b = rows.get(m['bot_b'], 1500)
                    # compute score_a_norm
                    if score_a > score_b:
                        s_a = 1.0
                    elif score_a < score_b:
                        s_a = 0.0
                    else:
                        s_a = 0.5
                    new_a, new_b = elo_update(r_a, r_b, s_a)
                    # update ratings in transaction
                    cursor.execute("UPDATE bots SET rating=%s WHERE id=%s", (new_a, m['bot_a']))
                    cursor.execute("UPDATE bots SET rating=%s WHERE id=%s", (new_b, m['bot_b']))
                    cursor.execute("UPDATE matches SET status='done' WHERE id=%s", (m['id'],))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    cursor.execute("UPDATE matches SET status='failed' WHERE id=%s", (m['id'],))
                    conn.commit()
    finally:
        conn.close()

def start_scheduler(app, interval_seconds=60):
    scheduler.add_job(run_scheduled_matches, 'interval', seconds=interval_seconds, id='ladder_runner', max_instances=1)
    scheduler.start()