from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def dashboard():
    total_items = 230
    inspection_items = 5
    return render_template('dashboard.html',
                           total_items=total_items,
                           inspection_items=inspection_items)

if __name__ == '__main__':
    app.run(debug=True)
