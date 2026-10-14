import os

from app import create_app, socketio

# The debug reloader imports this entrypoint in both its watcher and child.
# Only the serving child may start jobs; the watcher survives child reloads.
start_background_jobs = __name__ != '__main__' or os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
app = create_app(start_background_jobs=start_background_jobs)

if __name__ == '__main__':
    socketio.run(app, host='localhost', port=5000, debug=True, use_reloader=True, allow_unsafe_werkzeug=True)  # TODO : use other web server in production
