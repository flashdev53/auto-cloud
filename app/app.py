from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "Hello from Auto-Cloud CI/CD!"

@app.route("/health")
def health():
    return "OK", 200
