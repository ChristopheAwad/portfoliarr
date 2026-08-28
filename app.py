# Import the Flask class (used to create the app) and the render_template
# helper (used to serve Jinja2 HTML templates to the browser).
from flask import Flask, render_template

# Create the Flask application instance named "app". This object holds the
# routes, config, and is what runs our web server.
app = Flask(__name__)


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


# This guard only runs the block when app.py is executed directly, not
# when it is imported by another module.
if __name__ == "__main__":
    # Start the built-in Flask development server, with debug mode enabled
    # (auto-reloads on code changes and shows detailed error pages).
    app.run(debug=True)
