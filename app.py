from flask import Flask, render_template, request

app = Flask(__name__)

# Dummy data
materiaal_items = 230
keuring_items = 5

@app.route('/')
def dashboard():
    query = request.args.get('query', '')
    return render_template(
        'dashboard.html',
        materiaal_items=materiaal_items,
        keuring_items=keuring_items,
        query=query
    )

@app.route('/materiaal')
def materiaal():
    return render_template('materiaal.html')

@app.route('/keuringen')
def keuringen():
    return render_template('keuringen.html')

if __name__ == '__main__':
    app.run(debug=True)
