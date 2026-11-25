from flask import Flask, request, redirect, url_for, render_template_string, flash
import sqlite3
import requests
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = "farmcue-local-demo-key"
DB_NAME = "farmcue.db"

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FarmCue | Smart Farm Reminders</title>
<style>
:root{--green:#236b3b;--light:#eef7ee;--dark:#173d25;--gold:#f2b84b}
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:#f5f7f2;color:#26352a}
header{background:var(--dark);color:white;padding:22px 6%;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap}
header h1{margin:0;font-size:27px}header p{margin:5px 0 0;color:#d8eadb}
nav a{color:white;text-decoration:none;margin:0 9px;font-weight:bold}
main{max-width:1150px;margin:28px auto;padding:0 18px}
.hero{background:linear-gradient(120deg,#236b3b,#73a85d);color:white;padding:28px;border-radius:16px;margin-bottom:22px}
.hero h2{font-size:27px;margin:0 0 8px}.hero p{margin:0;line-height:1.5}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin:18px 0}
.card{background:white;border-radius:13px;padding:20px;box-shadow:0 3px 14px #183b2412}
.card h3{margin-top:0;color:var(--green)}.metric{font-size:30px;font-weight:bold;color:var(--dark)}
form{display:grid;gap:11px}label{font-weight:bold;font-size:14px}
input,select{width:100%;padding:11px;border:1px solid #cbd7ca;border-radius:8px;font-size:15px}
button,.btn{background:var(--green);color:white;border:0;padding:11px 16px;border-radius:8px;cursor:pointer;text-decoration:none;display:inline-block;font-weight:bold}
button:hover,.btn:hover{background:#174d2b}.btn.secondary{background:#60766a}.btn.warning{background:#b7791f}
table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:12px;border-bottom:1px solid #e4ebe2}th{background:var(--light);color:var(--dark)}
.badge{display:inline-block;padding:5px 9px;border-radius:20px;font-size:12px;font-weight:bold;background:#e6f4e8;color:#236b3b}
.badge.done{background:#e5e7eb;color:#4b5563}.badge.alert{background:#fff1d6;color:#8a5600}
.notice{padding:12px;border-radius:8px;background:#fff1d6;margin:10px 0}.good{background:#e7f5e8}
.small{font-size:13px;color:#66736a}.actions{display:flex;gap:7px;flex-wrap:wrap}
@media(max-width:650px){header{gap:15px}nav a{display:inline-block;margin:6px 7px 0 0}table{font-size:13px}th,td{padding:8px}}
</style>
</head>
<body>
<header>
 <div><h1>🌱 FarmCue</h1><p>Weather-Based Farm Task Reminder</p></div>
 <nav><a href="/">Dashboard</a><a href="/tasks">Farm Tasks</a><a href="/weather">Weather</a></nav>
</header>
<main>
{% with messages = get_flashed_messages() %}{% if messages %}{% for m in messages %}<div class="notice good">{{m}}</div>{% endfor %}{% endif %}{% endwith %}
{{ body|safe }}
</main>
</body></html>
"""

def db():
    con = sqlite3.connect(DB_NAME)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, crop TEXT NOT NULL, plot TEXT NOT NULL,
            task_date TEXT NOT NULL, task_type TEXT NOT NULL,
            notes TEXT DEFAULT '', status TEXT DEFAULT 'Pending',
            recommendation TEXT DEFAULT ''
        )""")

def get_weather(city="Bengaluru"):
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=10
    )
    geo.raise_for_status()
    places = geo.json().get("results", [])
    if not places:
        raise ValueError("City not found. Try a nearby major city name.")
    place = places[0]
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
            "daily": "precipitation_probability_max,precipitation_sum,temperature_2m_max,wind_speed_10m_max",
            "timezone": "auto", "forecast_days": 1
        }, timeout=10
    )
    forecast.raise_for_status()
    data = forecast.json()
    return place, data

def weather_advice(task_type, weather_data):
    daily = weather_data.get("daily", {})
    rain_chance = (daily.get("precipitation_probability_max") or [0])[0] or 0
    rain_mm = (daily.get("precipitation_sum") or [0])[0] or 0
    max_temp = (daily.get("temperature_2m_max") or [0])[0] or 0
    max_wind = (daily.get("wind_speed_10m_max") or [0])[0] or 0
    kind = task_type.lower()

    if ("spray" in kind or "pesticide" in kind) and (rain_chance >= 50 or max_wind >= 20):
        return f"Consider rescheduling: rain chance is {rain_chance}% and maximum wind is {max_wind} km/h. Check product label and local advice."
    if ("sow" in kind or "plant" in kind) and rain_mm > 20:
        return f"Consider checking field conditions before sowing: forecast rainfall is {rain_mm} mm."
    if ("water" in kind or "irrigat" in kind) and rain_chance >= 60:
        return f"Review irrigation: rain chance is {rain_chance}%, so watering may not be needed."
    if max_temp >= 38:
        return f"Heat caution: forecast maximum temperature is {max_temp}°C. Consider cooler working hours and protect workers."
    return f"No major rule-based warning detected. Rain chance: {rain_chance}%, max temperature: {max_temp}°C. Confirm conditions locally."

@app.route("/")
def home():
    with db() as con:
        tasks = con.execute("SELECT * FROM tasks ORDER BY task_date LIMIT 6").fetchall()
        total = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        pending = con.execute("SELECT COUNT(*) FROM tasks WHERE status='Pending'").fetchone()[0]
        completed = con.execute("SELECT COUNT(*) FROM tasks WHERE status='Completed'").fetchone()[0]
    rows = "".join(
        f"<tr><td>{t['title']}</td><td>{t['crop']}</td><td>{t['task_date']}</td><td>{t['status']}</td></tr>"
        for t in tasks
    ) or "<tr><td colspan='4'>No tasks added yet. Add your first farm task.</td></tr>"
    body = f"""
    <section class="hero"><h2>Plan smarter. Farm better.</h2>
    <p>Keep track of farm activities and review weather-based reminders before doing important field work.</p></section>
    <div class="grid">
      <div class="card"><h3>Total Tasks</h3><div class="metric">{total}</div></div>
      <div class="card"><h3>Pending Tasks</h3><div class="metric">{pending}</div></div>
      <div class="card"><h3>Completed Tasks</h3><div class="metric">{completed}</div></div>
    </div>
    <div class="card"><h3>Upcoming Farm Tasks</h3>
    <table><tr><th>Task</th><th>Crop</th><th>Date</th><th>Status</th></tr>{rows}</table>
    <p style="margin-top:16px"><a class="btn" href="/tasks">Manage Farm Tasks</a> <a class="btn secondary" href="/weather">Check Weather</a></p></div>
    <p class="small">Weather suggestions are rule-based guidance, not guaranteed predictions. Farmers should verify local conditions before acting.</p>
    """
    return render_template_string(HTML, body=body)

@app.route("/tasks", methods=["GET", "POST"])
def tasks_page():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        crop = request.form.get("crop", "").strip()
        plot = request.form.get("plot", "").strip()
        task_date = request.form.get("task_date", "").strip()
        task_type = request.form.get("task_type", "").strip()
        notes = request.form.get("notes", "").strip()
        if not all([title, crop, plot, task_date, task_type]):
            flash("Please fill in all required fields.")
        else:
            with db() as con:
                con.execute("""INSERT INTO tasks(title,crop,plot,task_date,task_type,notes)
                    VALUES(?,?,?,?,?,?)""", (title,crop,plot,task_date,task_type,notes))
            flash("Farm task added successfully.")
            return redirect(url_for("tasks_page"))

    with db() as con:
        all_tasks = con.execute("SELECT * FROM tasks ORDER BY task_date").fetchall()
    rows = ""
    for t in all_tasks:
        rec = f"<div class='notice'>{t['recommendation']}</div>" if t["recommendation"] else ""
        status = "done" if t["status"] == "Completed" else ""
        rows += f"""<tr><td>{t['title']}<div class='small'>{t['notes']}</div>{rec}</td>
        <td>{t['crop']}<div class='small'>Plot: {t['plot']}</div></td><td>{t['task_type']}</td>
        <td>{t['task_date']}</td><td><span class='badge {status}'>{t['status']}</span></td>
        <td><div class='actions'>
        <form method='post' action='/complete/{t['id']}'><button type='submit'>Complete</button></form>
        <form method='post' action='/delete/{t['id']}' onsubmit=\"return confirm('Delete this task?')\"><button class='btn warning' type='submit'>Delete</button></form>
        </div></td></tr>"""
    if not rows:
        rows = "<tr><td colspan='6'>No tasks available.</td></tr>"
    body = f"""
    <div class="grid">
      <section class="card"><h3>Add a Farm Task</h3>
      <form method="post">
       <label>Task name *</label><input name="title" placeholder="Example: Spray tomato field" required>
       <label>Crop *</label><input name="crop" placeholder="Example: Tomato" required>
       <label>Plot / Field *</label><input name="plot" placeholder="Example: Plot A" required>
       <label>Task date *</label><input type="date" name="task_date" min="{date.today().isoformat()}" required>
       <label>Task type *</label><select name="task_type" required>
        <option value="">Select task type</option><option>Sowing</option><option>Planting</option>
        <option>Spraying</option><option>Pesticide application</option><option>Watering</option>
        <option>Irrigation</option><option>Harvesting</option><option>Fertilizing</option><option>Other</option>
       </select>
       <label>Notes</label><input name="notes" placeholder="Optional details">
       <button type="submit">Add Task</button>
      </form></section>
      <section class="card"><h3>Weather-Based Reminder</h3>
      <p>Open the Weather page to review forecast conditions and get a rule-based suggestion for each pending task.</p>
      <a class="btn" href="/weather">Check Weather & Suggestions</a>
      <p class="small">Suggestions are advisory. Confirm weather, crop stage and product instructions before changing farm activities.</p></section>
    </div>
    <section class="card"><h3>Task Calendar / Task List</h3><div style="overflow-x:auto">
    <table><tr><th>Task</th><th>Crop / Plot</th><th>Type</th><th>Date</th><th>Status</th><th>Action</th></tr>{rows}</table></div></section>
    """
    return render_template_string(HTML, body=body)

@app.route("/complete/<int:task_id>", methods=["POST"])
def complete_task(task_id):
    with db() as con:
        con.execute("UPDATE tasks SET status='Completed' WHERE id=?", (task_id,))
    flash("Task marked as completed.")
    return redirect(url_for("tasks_page"))

@app.route("/delete/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    with db() as con:
        con.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    flash("Task deleted.")
    return redirect(url_for("tasks_page"))

@app.route("/weather", methods=["GET", "POST"])
def weather_page():
    city = request.values.get("city", "Bengaluru").strip() or "Bengaluru"
    try:
        place, data = get_weather(city)
        current = data.get("current", {})
        daily = data.get("daily", {})
        temp = current.get("temperature_2m", "N/A")
        humidity = current.get("relative_humidity_2m", "N/A")
        rain = current.get("precipitation", "N/A")
        wind = current.get("wind_speed_10m", "N/A")
        rain_chance = (daily.get("precipitation_probability_max") or ["N/A"])[0]
        rain_sum = (daily.get("precipitation_sum") or ["N/A"])[0]
        max_temp = (daily.get("temperature_2m_max") or ["N/A"])[0]
        with db() as con:
            pending = con.execute("SELECT * FROM tasks WHERE status='Pending' ORDER BY task_date").fetchall()
            for task in pending:
                advice = weather_advice(task["task_type"], data)
                con.execute("UPDATE tasks SET recommendation=? WHERE id=?", (advice, task["id"]))
        advice_rows = "".join(
            f"<tr><td>{t['title']}</td><td>{t['task_type']}</td><td>{t['task_date']}</td><td>{weather_advice(t['task_type'], data)}</td></tr>"
            for t in pending
        ) or "<tr><td colspan='4'>No pending tasks. Add tasks to receive reminders.</td></tr>"
        body = f"""
        <section class="card"><h2>Weather Forecast</h2>
        <form method="get" style="display:flex;grid-template-columns:1fr auto;align-items:end">
         <div><label>Enter city</label><input name="city" value="{city}" placeholder="Bengaluru"></div>
         <button type="submit">Get Weather</button>
        </form>
        <h3>{place['name']}, {place.get('country','')}</h3>
        <div class="grid">
         <div class="card"><h3>Current Temperature</h3><div class="metric">{temp} °C</div></div>
         <div class="card"><h3>Humidity</h3><div class="metric">{humidity}%</div></div>
         <div class="card"><h3>Current Rain</h3><div class="metric">{rain} mm</div></div>
         <div class="card"><h3>Wind Speed</h3><div class="metric">{wind} km/h</div></div>
        </div>
        <div class="notice good">Today's forecast: rain probability {rain_chance}% | rainfall {rain_sum} mm | maximum temperature {max_temp} °C.</div>
        <p class="small">Forecast supplied by Open-Meteo. Weather data may change and may not represent the exact conditions in your field.</p>
        </section>
        <section class="card"><h3>Weather-Based Task Suggestions</h3><div style="overflow-x:auto">
        <table><tr><th>Task</th><th>Type</th><th>Planned Date</th><th>Suggestion</th></tr>{advice_rows}</table></div>
        <p class="small">FarmCue does not automatically change task dates. The farmer makes the final decision.</p></section>
        """
    except Exception as e:
        body = f"""<section class="card"><h2>Weather service unavailable</h2>
        <div class="notice">Could not retrieve weather for "{city}". Check your internet connection and city name, then try again.</div>
        <p class="small">Technical detail: {str(e)}</p><a class="btn" href="/weather">Try Again</a></section>"""
    return render_template_string(HTML, body=body)

if __name__ == "__main__":
    init_db()
    print("FarmCue is starting. Open http://127.0.0.1:5000 in your browser.")
    app.run(debug=True)
