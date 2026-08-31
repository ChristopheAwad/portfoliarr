# Import the Flask class (used to create the app), render_template (serves
# Jinja2 HTML templates to the browser), and jsonify (converts Python
# dicts/lists into a proper JSON HTTP response, including the
# Content-Type: application/json header).
from flask import Flask, jsonify, render_template

# Import our data layer (market_data.py). This file is the "route layer":
# it decides WHICH symbols the page needs; market_data.py handles the HOW
# of fetching and caching.
from market_data import get_quote

# Create the Flask application instance named "app". This object holds the
# routes, config, and is what runs our web server.
app = Flask(__name__)

# The symbols shown in the dashboard's indices bar. This is a product
# decision (which markets the bar tracks), so it lives in the route layer,
# not in the generic data module. Adding a chip = adding a string here AND
# a matching data-symbol attribute on the chip in templates/index.html.
INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^GSPTSE", "BTC-USD"]


# The @app.route decorator registers this function as the handler for the
# root URL "/" (e.g. http://localhost:5000/).
@app.route("/")
# Define the "index" view function. Flask calls it whenever the root URL
# is requested, and its return value becomes the HTTP response.
def index():
    # Initialize an empty list to hold the user's portfolio/watchlist
    # securities. Currently a placeholder for the MVP.
    watchlist = []
    # Render "index.html" and pass the watchlist into the template context
    # so the template can display it.
    return render_template("index.html", watchlist=watchlist)


# JSON endpoint that powers the live indices bar. The browser's JavaScript
# fetches this URL. Returns a JSON *list* of quote dicts.
@app.route("/api/indices")
def index_quotes():
    # Per-symbol resilience: each chip is fetched independently, so one
    # dead symbol cannot blank the whole bar. Failures are skipped.
    quotes = []
    failures = 0
    for symbol in INDEX_SYMBOLS:
        try:
            quotes.append(get_quote(symbol))
        except Exception:
            # Boundary rule: catch WIDE at the edge of the system (yfinance
            # can fail in many ways) and degrade gracefully, per symbol.
            failures += 1

    # Only when EVERY symbol fails is the whole endpoint considered sick:
    # 503 = "Service Unavailable — it's me, not you, try again later."
    if failures == len(INDEX_SYMBOLS):
        return jsonify({"error": "quote service unavailable"}), 503

    # Successes only: failed symbols are simply absent from the list.
    # The frontend infers which chips to mark unavailable ("—").
    return jsonify(quotes)


# This guard only runs the block when app.py is executed directly, not
# when it is imported by another module.
if __name__ == "__main__":
    # Start the built-in Flask development server, with debug mode enabled
    # (auto-reloads on code changes and shows detailed error pages).
    app.run(debug=True)
