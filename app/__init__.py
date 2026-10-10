from flask import Flask
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import logging
import os

from dotenv import load_dotenv

# Loaded here rather than in run.py: ALLOWED_ORIGINS below is evaluated at
# import time, and run.py's `from app import ...` has already executed this
# whole module before its own top-level code could call load_dotenv().
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

_DEFAULT_ORIGINS = 'http://localhost:5000,http://127.0.0.1:5000'
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', _DEFAULT_ORIGINS).split(',')
if 'ALLOWED_ORIGINS' not in os.environ:
    # Browsers omit the Origin header on same-origin GET but send it on POST,
    # so an unset value looks like a working handshake followed by 400s on
    # every poll POST — with no application error to find.
    print("WARNING: ALLOWED_ORIGINS is not set; falling back to %s. SocketIO "
          "POSTs from any other origin will be rejected with 400 'Not an "
          "accepted origin.'" % _DEFAULT_ORIGINS)
# The Werkzeug dev server's WebSocket upgrade (via simple-websocket) raises a
# ConnectionError and logs a spurious 500 traceback whenever a client that was
# upgraded to WebSocket disconnects abruptly (e.g. navigating away from a page
# with an open socket). Disable the polling->WebSocket upgrade so clients stay
# on long-polling, which already works reliably here.
socketio = SocketIO(cors_allowed_origins=ALLOWED_ORIGINS, allow_upgrades=False)
login_manager = LoginManager()

def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())
    app.debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    
    CORS(app, origins=ALLOWED_ORIGINS)
    socketio.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Build any C++ game judge binary that is missing or stale for this platform.
    from judges.build import ensure_judges_built
    ensure_judges_built()

    # Reclaim bot upload directories orphaned by an interrupted delete. Runs
    # before the scheduler so it can never race with a live match.
    from .upload import sweep_orphan_bot_dirs
    sweep_orphan_bot_dirs()

    from .home import register_home_events
    from .gomoku import register_gomoku_events
    from .tank2 import register_tank_events
    from .snake import register_snake_events
    from .tictactoe import register_tictactoe_events
    register_home_events(socketio)
    register_gomoku_events(socketio)
    register_tank_events(socketio)
    register_snake_events(socketio)
    register_tictactoe_events(socketio)

    from .main import main_bp
    from .home import home_bp
    from .auth import auth_bp
    from .upload import upload_bp
    from .gomoku import gomoku_bp
    from .tank2 import tank_bp
    from .snake import snake_bp
    from .tictactoe import tictactoe_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(gomoku_bp)
    app.register_blueprint(tank_bp)
    app.register_blueprint(snake_bp)
    app.register_blueprint(tictactoe_bp)

    start_scheduler(app)
    
    return app

def start_scheduler(app):
    """
    配置并启动 APScheduler 后台调度器。
    """
    from .services.battle_worker import schedule_all_games
    # 避免调度器日志污染您的控制台 (可选)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)

    # 使用 BackgroundScheduler，因为它在主线程之外运行，非常适合 Flask/SocketIO 应用
    scheduler = BackgroundScheduler()
    
    # === 添加定时任务 ===
    # 任务: 定期运行所有游戏的自动对战
    # trigger="interval" 表示间隔执行
    # minutes=30 表示每 30 分钟运行一次。您可以根据需求调整
    scheduler.add_job(
        func=schedule_all_games,
        trigger="interval",
        minutes=30, 
        id='auto_match_runner',
        name='Run Automated Game Matches'
    )
    
    # 启动调度器
    scheduler.start()

    # 注册一个退出函数，确保在 Flask 进程关闭时，调度器也安全停止
    atexit.register(lambda: scheduler.shutdown())
    
    print("APScheduler started: Automated match runner scheduled.")