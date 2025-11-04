from flask import Flask, render_template, render_template_string
app = Flask(__name__)

@app.route("/")
@app.route("/dashboard")
def dashboard():
    print("HIT /dashboard")  # moet in je console verschijnen bij refresh
    return render_template("dashboard.html", total_items=230, to_inspect=5)

@app.route("/materiaal")
def materiaal():
    return render_template("materiaal.html")

@app.route("/keuringen")
def keuringen():
    return render_template("keuringen.html")

if __name__ == "__main__":
    app.run(debug=True)
