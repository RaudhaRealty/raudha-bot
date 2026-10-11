import os
import threading
import logging
from flask import Flask
from bot import main as run_bot

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/')
def home():
    return "Raudha is running"

@app.route('/health')
def health():
    return "OK", 200

def start_bot():
    run_bot()

if __name__ == "__main__":
    # Jalankan bot di thread terpisah
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Jalankan Flask di port yang diberikan Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)