from flask import Flask
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import logging



socketio = SocketIO(cors_allowed_origins="*")
login_manager = LoginManager()

def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object('config.Config')  
    
    CORS(app)
    socketio.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    from .home import register_home_events
    from .gomoku import register_gomoku_events
    from .tank2 import register_tank_events
    from .snake import register_snake_events
    register_home_events(socketio)
    register_gomoku_events(socketio)
    register_tank_events(socketio)
    register_snake_events(socketio)

    from .main import main_bp
    from .home import home_bp
    from .auth import auth_bp
    from .upload import upload_bp
    from .gomoku import gomoku_bp
    from .tank2 import tank_bp
    from .snake import snake_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(gomoku_bp)
    app.register_blueprint(tank_bp)
    app.register_blueprint(snake_bp)

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
    # minutes=5 表示每 5 分钟运行一次。您可以根据需求调整
    scheduler.add_job(
        func=schedule_all_games,
        trigger="interval",
        minutes=1, 
        id='auto_match_runner',
        name='Run Automated Game Matches'
    )
    
    # 启动调度器
    scheduler.start()

    # 注册一个退出函数，确保在 Flask 进程关闭时，调度器也安全停止
    atexit.register(lambda: scheduler.shutdown())
    
    print("APScheduler started: Automated match runner scheduled.")