from flask import Flask

app = Flask(__name__)  # <-- this defines the Flask app that Flask looks for

@app.route('/')
def home():
    return "Hello, Flask is running successfully"

if __name__ == "__main__":
    app.run(debug=True)