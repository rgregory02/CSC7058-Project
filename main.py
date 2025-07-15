import os
import json
import shutil  # For moving files and folders
import time  # For unique timestamps

from flask import Flask, Response, jsonify, request, url_for, redirect, render_template, flash, get_flashed_messages, send_from_directory, render_template_string, session
from markupsafe import Markup, escape
from urllib.parse import quote, unquote
from datetime import datetime, timezone

def safe_date(x):
    try:
        dt = datetime.fromisoformat(x[2])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

try:
    from zoneinfo import ZoneInfo  # type: ignore[import]  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python 3.8 fallback
from utils import (
    load_json_as_dict,
    save_dict_as_json,
    get_readable_time,
    printButton,
    prettify,
    get_label_description
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'the_random_string')  # Use environment variable if available

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

@app.route('/types/<path:filename>')
def serve_type_images(filename):
    return send_from_directory('types', filename)


from flask import render_template
from datetime import datetime
import os
from utils import load_json_as_dict  # adjust if your utility function is elsewhere

@app.route('/')
def index_page():
    person_bios = []
    types = []

    # Load available types
    for file in os.listdir("./types"):
        if file.endswith(".json") and os.path.splitext(file)[0].lower() != "time":
            types.append(os.path.splitext(file)[0])

    # Load person bios
    person_dir = "./types/person/biographies"
    if os.path.exists(person_dir):
        for af in os.listdir(person_dir):
            if af.endswith(".json"):
                agg_id = af[:-5]
                data = load_json_as_dict(os.path.join(person_dir, af))
                name = data.get("name", agg_id.replace("_", " "))
                created = data.get("created", "")  # ISO string
                person_bios.append((agg_id, name, created))

    # Sort by safe parsed date (newest first)
    person_bios.sort(key=safe_date, reverse=True)

    return render_template("index.html", types=types, person_bios=person_bios)

@app.route("/global_search")
def global_search():
    query = request.args.get("q", "").lower()
    page = int(request.args.get("page", 1))
    per_page = 10

    results = []
    person_dir = "./types/person/biographies"

    if query and os.path.exists(person_dir):
        for file in os.listdir(person_dir):
            if not file.endswith(".json"):
                continue

            try:
                full_path = os.path.join(person_dir, file)
                data = load_json_as_dict(full_path)
                name = data.get("name", "").lower()
                matched = False

                # Check name
                if query in name:
                    matched = True

                # Check entries in all known sections
                for section in ["time", "people", "organisations", "buildings"]:
                    for entry in data.get(section, []):
                        # Only try .values() if it's a dictionary
                        if isinstance(entry, dict):
                            searchable = [str(v).lower() for v in entry.values()]
                            if any(query in val for val in searchable if isinstance(val, str)):
                                matched = True
                                break
                        elif isinstance(entry, str) and query in entry.lower():
                            matched = True
                            break

                if matched:
                    results.append((file[:-5], data.get("name", file[:-5])))

            except Exception as e:
                print(f"Error searching {file}: {e}")
                continue

    # Remove duplicates
    results = list(dict(results).items())

    # Paginate
    start = (page - 1) * per_page
    end = start + per_page
    paginated = results[start:end]
    total_pages = (len(results) + per_page - 1) // per_page

    return render_template(
        "global_search.html",
        query=query,
        results=paginated,
        page=page,
        total_pages=total_pages
    )

@app.route("/api/search_person_bios")
def api_search_person_bios():
    query = request.args.get("q", "").lower()
    person_dir = "./types/person/biographies"
    matches = []

    if query and os.path.exists(person_dir):
        for file in os.listdir(person_dir):
            if not file.endswith(".json"):
                continue
            try:
                data = load_json_as_dict(os.path.join(person_dir, file))
                name = data.get("name", "").lower()
                if query in name:
                    matches.append({
                        "person_id": file[:-5],
                        "name": data.get("name", file[:-5])
                    })
            except:
                continue

    return jsonify(matches[:10])  # Return only first 10 matches for speed

@app.route('/person_iframe_wizard')
def person_iframe_wizard():
    step = request.args.get("step", "0")
    person_id = request.args.get("person_id") or session.get("person_id")

    # Restore person_id from query/session and preload data
    if person_id:
        session["person_id"] = person_id
        file_path = f"./types/person/biographies/{person_id}.json"
        if os.path.exists(file_path):
            existing_data = load_json_as_dict(file_path)
            session["person_name"] = existing_data.get("name", "")
        else:
            return f"Person ID {person_id} not found", 404

    print(f"[Wizard Step] {step} – Person ID: {session.get('person_id')}")

    if step == "0":
        # New name entry — reset time in progress
        session.pop("time_step_in_progress", None)
        return render_template("person_step_name.html", person_id=person_id)

    elif step == "1":
        # Create draft file if not already saved
        if not person_id and 'person_name' in session:
            session['person_id'] = f"Person_{int(time.time())}"
            person_id = session['person_id']
            now_uk = datetime.now(ZoneInfo("Europe/London")).isoformat()
            file_path = f"./types/person/biographies/{person_id}.json"
            save_dict_as_json(file_path, {
                "person_id": person_id,
                "name": session['person_name'],
                "created": now_uk,
                "entries": []
            })
        if not person_id:
            return redirect(url_for('person_iframe_wizard', step="0"))

        # ✅ Instead of redirecting to /person_step_time directly...
        return redirect(url_for('person_step_time', person_id=person_id))

    elif step == "final":
        if not person_id:
            return redirect(url_for('person_iframe_wizard', step="0"))
        return redirect(url_for('person_step_finalise', person_id=person_id))

    else:
        try:
            dynamic_types = sorted([
                t for t in os.listdir("./types")
                if os.path.isdir(f"./types/{t}") and t not in ["person", "time"]
            ])
            step_index = int(step) - 2

            # ✅ Only proceed if a valid time label has been selected
            if not session.get("time_selection"):
                print("[WARN] Cannot continue — missing time_selection")
                return redirect(url_for('person_iframe_wizard', step="1"))

            if 0 <= step_index < len(dynamic_types):
                return redirect(url_for('person_step_dynamic', step=step_index))
        except Exception as e:
            print(f"[Wizard Error] {e}")

        return redirect(url_for('person_iframe_wizard', step="0"))


@app.route("/person_edit_start/<person_id>")
def person_edit_start(person_id):
    """
    Resumes the person biography wizard for a given person_id, allowing addition of a new timepoint.
    """
    file_path = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(file_path):
        return f"<h1>Person Biography '{person_id}' Not Found</h1>", 404

    # Load existing person biography to repopulate session
    person_data = load_json_as_dict(file_path)
    session['person_id'] = person_id
    session['person_name'] = person_data.get("name", "[Unknown]")

    # Go directly to Step 1 (Time)
    return redirect(url_for('person_iframe_wizard', step="1"))


@app.route('/start_person_naming', methods=['GET', 'POST'])
def start_person_naming():
    if request.method == 'POST':
        name = request.form.get("person_name", "").strip()

        # ✅ Basic validation: name must not be empty
        if not name:
            return "<p>Please enter a name.</p>"

        # 🧹 Clear previous session data
        session.pop('person_id', None)
        session['person_name'] = name

        # 🚀 Proceed to confirmation step — file not saved yet
        return redirect("/person_iframe_wizard?step=0")

    # 🖼️ Display the name entry form
    return render_template("start_person_naming.html")

@app.route("/person_step/time/<person_id>", methods=["GET", "POST"])
def person_step_time(person_id):
    labels_folder = "./types/time/labels"
    person_folder = "./types/person/biographies"
    os.makedirs(labels_folder, exist_ok=True)
    os.makedirs(person_folder, exist_ok=True)

    person_file = os.path.join(person_folder, f"{person_id}.json")
    if not os.path.exists(person_file):
        return f"Person biography {person_id} not found.", 404

    person_data = load_json_as_dict(person_file)
    name = person_data.get("name", "[Unknown]")

    selected_label_type = request.form.get("label_type") or request.args.get("label_type", "").strip()
    selected_subvalue = request.form.get("subvalue", "").strip()
    selected_date = request.form.get("date_value", "").strip()
    selected_confidence = request.form.get("confidence")

    # --- Handle submission ---
    if request.method == "POST":
        try:
            confidence_value = int(selected_confidence)
        except (TypeError, ValueError):
            confidence_value = None

        valid_entry = (
            confidence_value is not None and
            (
                (selected_label_type == "date" and selected_date) or
                (selected_label_type != "date" and selected_subvalue)
            )
        )

        if valid_entry:
            time_entry = {
                "label_type": selected_label_type,
                "confidence": confidence_value
            }

            if selected_label_type == "date":
                time_entry["date_value"] = selected_date
                label_value = selected_date
            else:
                time_entry["subvalue"] = selected_subvalue
                label_value = selected_subvalue

            # Save to session only
            session["time_selection"] = {
                "label": label_value,
                "confidence": confidence_value,
                "label_type": selected_label_type,
                "date_value": selected_date if selected_label_type == "date" else "",
                "subvalue": selected_subvalue if selected_label_type != "date" else ""
            }
            session["person_id"] = person_id
            session["person_name"] = name
            session["time_step_in_progress"] = True

            print(f"[DEBUG] Time label saved to session: {session['time_selection']}")
            return redirect("/person_iframe_wizard?step=2")
        else:
            print("[WARN] Invalid time entry submission — missing confidence or value")

    # --- Load dropdown label options ---
    label_files = []
    if os.path.exists(labels_folder):
        for file in os.listdir(labels_folder):
            full_path = os.path.join(labels_folder, file)
            if file.endswith(".json") and os.path.isfile(full_path):
                try:
                    with open(full_path) as f:
                        data = json.load(f)
                        label = os.path.splitext(file)[0]
                        desc = data.get("description", "")
                        label_files.append((label, desc))
                except Exception as e:
                    print(f"[ERROR] Failed to load label {file}: {e}")

    # --- Load sublabels for the selected label type ---
    subfolder_labels = []
    if selected_label_type and selected_label_type != "date":
        subfolder_path = os.path.join(labels_folder, selected_label_type)
        if os.path.isdir(subfolder_path):
            subfolder_labels = [
                os.path.splitext(f)[0]
                for f in os.listdir(subfolder_path)
                if f.endswith(".json")
            ]

    # --- Show existing time entries from person_data["entries"] ---
    display_list = []
    for entry in person_data.get("entries", []):
        time_info = entry.get("time", {})
        tag = time_info.get("subvalue") or time_info.get("date_value") or "[unspecified]"
        conf = time_info.get("confidence", "unknown")
        display_list.append((tag, conf))

    return render_template(
        "person_step_time.html",
        person_id=person_id,
        name=name,
        label_files=label_files,
        selected_label_type=selected_label_type,
        selected_subvalue=selected_subvalue,
        selected_date=selected_date,
        selected_confidence=selected_confidence,
        subfolder_labels=subfolder_labels,
        existing_entries=display_list
    )


@app.route("/person_step/dynamic/<int:step>", methods=["GET", "POST"])
def person_step_dynamic(step):
    person_id = session.get("person_id")
    if not person_id:
        return redirect(url_for("person_iframe_wizard", step="0"))

    person_file = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(person_file):
        return f"Person file {person_id} not found", 404

    person_data = load_json_as_dict(person_file)
    person_data.setdefault("entries", [])

    # 🚫 Prevent jumping to step 0 without a valid time selection
    if step == 0 and not session.get("time_selection"):
        print("[WARN] No time selection in session, redirecting to time step")
        return redirect(url_for("person_step_time", person_id=person_id))

    # ✅ Save time selection at step 0 every time
    if step == 0 and session.get("time_step_in_progress") and session.get("time_selection"):
        person_data["entries"].append({
            "time": session["time_selection"]
        })
        save_dict_as_json(person_file, person_data)
        print("[DEBUG] New time entry written to JSON from session.")
        session["time_step_in_progress"] = False

    # Load current type folder
    type_folders = sorted([
        t for t in os.listdir("./types")
        if os.path.isdir(f"./types/{t}") and t != "time"
    ])

    if step >= len(type_folders):
        return redirect(url_for("finalise_person_bio"))

    current_type = type_folders[step]
    label_base_path = f"./types/{current_type}/labels"
    bio_path = f"./types/{current_type}/biographies"

    # Load biography options
    biography_options = []
    if os.path.exists(bio_path):
        for f in os.listdir(bio_path):
            if f.endswith(".json"):
                bio_id = f[:-5]
                display_name = bio_id.replace("_", " ")
                biography_options.append({"id": bio_id, "display": display_name})

    # Load label groups from subfolders only
    label_groups = {}
    label_groups_list = []
    seen_keys = set()

    if os.path.exists(label_base_path):
        for file in os.listdir(label_base_path):
            key = os.path.splitext(file)[0]
            if not key or key == "undefined" or key in seen_keys:
                continue
            seen_keys.add(key)

            values = []
            folder_path = os.path.join(label_base_path, key)
            if os.path.isdir(folder_path):
                for entry in os.listdir(folder_path):
                    if entry.endswith(".json"):
                        base = entry[:-5]
                        json_path = os.path.join(folder_path, entry)
                        img_path = os.path.join(folder_path, f"{base}.jpg")
                        try:
                            data = load_json_as_dict(json_path)
                            label = {
                                "id": base,
                                "display": data.get("properties", {}).get("name", base)
                            }
                            if os.path.exists(img_path):
                                label["image"] = f"/types/{current_type}/labels/{key}/{base}.jpg"
                            values.append(label)
                        except Exception as e:
                            print(f"[ERROR] Reading label {entry}: {e}")

            if values:
                label_dict = {
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "options": values
                }
                label_groups[key] = label_dict
                label_groups_list.append(label_dict)

    # ✅ Handle POST submission
    if request.method == "POST":
        new_entries = []

        selected_bio_id = request.form.get("selected_id_biography")
        if selected_bio_id:
            new_entries.append({
                "id": selected_bio_id,
                "confidence": 100,
                "source": "biography"
            })

        for group in label_groups_list:
            key = group["key"]
            selected_id = request.form.get(f"selected_id_{key}")
            confidence = int(request.form.get(f"confidence_{key}", 80))
            if selected_id:
                new_entries.append({
                    "id": selected_id,
                    "confidence": confidence
                })

        if new_entries and person_data.get("entries"):
            latest = person_data["entries"][-1]
            latest.setdefault(current_type, [])
            latest[current_type].extend(new_entries)
            save_dict_as_json(person_file, person_data)

        return redirect(url_for("person_step_dynamic", step=step + 1))

    # Final render
    existing_labels = []
    if person_data.get("entries"):
        latest = person_data["entries"][-1]
        existing_labels = latest.get(current_type, [])

    return render_template(
        "person_step_dynamic.html",
        current_type=current_type,
        biography_options=biography_options,
        label_groups=label_groups,
        label_groups_list=label_groups_list,
        existing_labels=existing_labels,
        person_id=person_id,
        skip_allowed=(len(label_groups_list) == 0 and len(biography_options) == 0),
        person_name=person_data.get("name", person_id),
        time_selection=session.get("time_selection"),
        next_step=step + 1,
        prev_step=step - 1 if step > 0 else None
    )


@app.route("/person_add_timepoint/<person_id>")
def person_add_timepoint(person_id):
    """
    Resets session state so the next time period starts fresh.
    """
    session["time_step_in_progress"] = False  # Start a new timepoint
    session["time_selection"] = None  # Optional: clear previous label preview
    session["person_id"] = person_id  # Ensure person_id remains in session
    return redirect(url_for("person_step_time", person_id=person_id))

@app.route("/person_delete_entry/<person_id>/<int:entry_index>")
def person_delete_entry(person_id, entry_index):
    file_path = f"./types/person/biographies/{person_id}.json"
    person_data = load_json_as_dict(file_path)

    if 0 <= entry_index < len(person_data.get("entries", [])):
        person_data["entries"].pop(entry_index)
        save_dict_as_json(file_path, person_data)

    return redirect(url_for("person_view", aggregator_id=person_id))


@app.route("/person_edit_timepoint/<person_id>/<int:entry_index>")
def person_edit_timepoint(person_id, entry_index):
    # Load the file and entry, then redirect to step 1 preloaded
    # Optional: Implement pre-population logic here
    return redirect(url_for("person_step_time", person_id=person_id))


@app.route("/archived_people")
def view_archived_people():
    archived_folder = "./types/person/biographies/archived"
    archived_people = []

    if os.path.exists(archived_folder):
        for file in os.listdir(archived_folder):
            if file.endswith(".json"):
                path = os.path.join(archived_folder, file)
                try:
                    with open(path) as f:
                        data = json.load(f)
                        person_id = os.path.splitext(file)[0]
                        name = data.get("name", "[Unnamed]")
                        created = data.get("created")
                        archived_people.append((person_id, name, created))
                except Exception as e:
                    print(f"[ERROR] Couldn't load archived bio {file}: {e}")

    # ✅ Make sure the HTML file is named `archived_biographies.html`
    return render_template("archived_biographies.html", archived_people=archived_people)

@app.route("/archive_person/<person_id>")
def archive_person(person_id):
    active_path = f"./types/person/biographies/{person_id}.json"
    archive_path = f"./types/person/biographies/archived/{person_id}.json"

    if not os.path.exists(active_path):
        return "Biography not found.", 404

    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    os.rename(active_path, archive_path)

    return redirect("/")

@app.route("/person_view_archived/<person_id>")
def view_archived_person(person_id):
    archive_path = f"./types/person/biographies/archived/{person_id}.json"
    if not os.path.exists(archive_path):
        return "Archived biography not found.", 404

    try:
        with open(archive_path) as f:
            data = json.load(f)
    except Exception as e:
        return f"Error loading archived biography: {e}", 500

    entries = data.get("entries", [])
    return render_template("person_view_archived.html", person_name=data.get("name", "Unnamed"), person_id=person_id, entries=entries)

@app.route("/restore_person/<person_id>")
def restore_archived_person(person_id):
    archive_path = f"./types/person/biographies/archived/{person_id}.json"
    active_path = f"./types/person/biographies/{person_id}.json"

    if not os.path.exists(archive_path):
        return "Archived biography not found.", 404

    try:
        os.rename(archive_path, active_path)
    except Exception as e:
        return f"Failed to restore biography: {e}", 500

    return redirect("/")

@app.route('/iframe_select_time')
def iframe_select_time():
    """
    Iframe step for selecting a time period from the types/time/labels folder.
    """
    label_dir = "./types/time/labels"
    time_options = []

    if os.path.exists(label_dir):
        for file in os.listdir(label_dir):
            if file.endswith(".json"):
                try:
                    label_path = os.path.join(label_dir, file)
                    data = load_json_as_dict(label_path)
                    label_name = data.get("name") or os.path.splitext(file)[0]
                    time_options.append(label_name)
                except Exception as e:
                    print(f"Error reading {file}: {e}")

    html = """
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>Select Time Period</title></head>
    <body>
      <h2>Step 1: Choose a Time Period</h2>
      <form action="/save_time_choice" method="post">
    """

    if time_options:
        for option in time_options:
            html += f"""
            <div>
              <input type="radio" name="time_choice" value="{option}" required>
              <label>{option}</label>
            </div>
            """
        html += """
            <br><button type="submit">Save & Continue</button>
        </form>
        """
    else:
        html += "<p><em>No time periods found in /types/time/labels</em></p>"

    html += "</body></html>"
    return html

@app.route('/save_time_choice', methods=['POST'])
def save_time_choice():
    choice = request.form.get("time_choice")
    if choice:
        session['person_bio_time'] = choice
    return redirect("/person_iframe_wizard?step=1")


@app.route('/iframe_select/<string:type_name>')
def iframe_select_type(type_name):
    """
    Displays a selector inside an iframe with:
    - Biography options (with optional images),
    - Confidence slider,
    - Optional label input.
    """
    import os, json

    biographies_path = f"./types/{type_name}/biographies"
    label_path = f"./types/{type_name}/labels"

    bios = []
    if os.path.exists(biographies_path):
        for file in os.listdir(biographies_path):
            if file.endswith(".json"):
                path = os.path.join(biographies_path, file)
                bio = load_json_as_dict(path)
                bios.append({
                    "id": bio.get("id", file[:-5]),
                    "name": bio.get("name", file[:-5]),
                    "image": bio.get("image", "")  # optional
                })

    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Select Item</title>
      <style>
        body { font-family: sans-serif; padding: 20px; }
        .bio-card {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 15px;
          padding: 10px;
          border: 1px solid #ccc;
          border-radius: 8px;
        }
        img {
          width: 64px; height: 64px;
          object-fit: cover;
          border-radius: 8px;
          background-color: #f0f0f0;
        }
        select, input[type='text'], input[type='range'] {
          margin-top: 8px;
          width: 100%;
          max-width: 300px;
        }
        .confidence-display {
          font-weight: bold;
          margin-top: 5px;
        }
      </style>
    </head>
    <body>
      <h2>Select from {type_name}</h2>
      <form method="post" action="/iframe_add_to_person">
        <input type="hidden" name="type" value="{type_name}">
        <label>Select an item:</label><br>
        <select name="item_id" required>
    """.replace("{type_name}", type_name.capitalize())

    for bio in bios:
        img_path = f"/serve_label_image/{type_name}/{bio['id']}/{bio['image']}" if bio['image'] else "/static/placeholder.png"
        html += f'<option value="{bio["id"]}">{bio["name"]}</option>'

    html += """
        </select><br><br>

        <label>Label (optional):</label><br>
        <input type="text" name="label" placeholder="e.g. inspired_by, mentor"><br><br>

        <label>Confidence:</label><br>
        <input type="range" id="confidence" name="confidence" min="0" max="100" value="80" oninput="document.getElementById('confVal').innerText = this.value + '%'">
        <div class="confidence-display">Confidence: <span id="confVal">80%</span></div>

        <br><br><button type="submit">Save & Return</button>
      </form>
    </body>
    </html>
    """

    return html

@app.route('/iframe_select_mostlike')
def iframe_select_mostlike():
    people_path = "./types/people/biographies"
    bios = []

    if os.path.exists(people_path):
        for file in os.listdir(people_path):
            if file.endswith(".json"):
                path = os.path.join(people_path, file)
                bio = load_json_as_dict(path)
                bios.append({
                    "id": bio.get("id", file[:-5]),
                    "name": bio.get("name", file[:-5]),
                    "image": bio.get("image", "")  # optional
                })

    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Most Like</title>
      <style>
        body { font-family: sans-serif; padding: 20px; }
        .card { display: flex; align-items: center; margin-bottom: 12px; border: 1px solid #ccc; padding: 10px; border-radius: 8px; }
        img { width: 60px; height: 60px; object-fit: cover; border-radius: 50%; margin-right: 15px; }
        select, input[type='range'] { width: 100%; max-width: 300px; }
        .confidence-display { font-weight: bold; margin-top: 5px; }
      </style>
    </head>
    <body>
      <h2>Choose the person you're most like</h2>
      <form method="post" action="/save_mostlike">
        <label>Person:</label><br>
        <select name="mostlike_id" required>
    """

    for bio in bios:
        html += f'<option value="{bio["id"]}">{bio["name"]}</option>'

    html += """
        </select><br><br>

        <label>Confidence:</label><br>
        <input type="range" name="confidence" min="0" max="100" value="75" oninput="document.getElementById('confShow').innerText = this.value + '%'">
        <div class="confidence-display">Confidence: <span id="confShow">75%</span></div>

        <br><button type="submit">Save and Continue</button>
      </form>
    </body>
    </html>
    """
    return html

@app.route('/save_mostlike', methods=['POST'])
def save_mostlike():
    mostlike_id = request.form.get("mostlike_id")
    confidence = request.form.get("confidence", "75")
    person_id = session.get("person_id")

    if not person_id:
        flash("No active person biography session", "danger")
        return redirect("/")

    person_file = f"./types/person/biographies/{person_id}.json"
    person_data = {}
    if os.path.exists(person_file):
        person_data = load_json_as_dict(person_file)

    person_data["mostlike"] = {
        "id": mostlike_id,
        "confidence": confidence
    }

    save_dict_as_json(person_file, person_data)

    return redirect("/person_iframe_wizard?step=2")

@app.route('/iframe_add_to_person', methods=['POST'])
def iframe_add_to_person():
    item = {
        "type": request.form["type"],
        "id": request.form["item_id"],
        "label": request.form.get("label", ""),
        "confidence": int(request.form.get("confidence", "80")) / 100.0
    }

    if "person_aggregator" not in session:
        session["person_aggregator"] = {"items": []}

    session["person_aggregator"]["items"].append(item)
    session.modified = True
    return "<script>window.top.location.href='/person_iframe_wizard';</script>"


@app.route('/finalise_person_bio')
def finalise_person_bio():
    person_id = session.get("person_id")
    if not person_id:
        return "<p>Error: No active person biography session.</p>"

    file_path = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(file_path):
        return "<p>Error: Draft biography file not found.</p>"

    # Load, mark as finalised, and save
    person = load_json_as_dict(file_path)
    person["finalised"] = True
    save_dict_as_json(file_path, person)

    # Store for the next step
    person_name = person.get("name", "Unnamed Person")

    # Optional: clear session variables
    session.pop("person_id", None)
    session.pop("person_name", None)
    session.pop("time_selection", None)

    return render_template(
        "finalise_person_bio.html",
        person_id=person_id,
        person_name=person_name
    )

@app.route('/person_view/<person_id>')
def person_view(person_id):
    """
    Displays a single person biography with entries grouped by time period,
    dynamically rendering associated types (people, buildings, labels, etc.)
    """
    person_file = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(person_file):
        return f"<h1>Person {person_id} Not Found</h1>", 404

    person_data = load_json_as_dict(person_file)
    person_name = person_data.get("name", f"Person {person_id}")

    def resolve_entities(type_name, entity_list):
        """
        Converts a list of label/link objects into display-friendly dicts.
        Handles both linked biographies and free-text labels.
        """
        resolved = []
        for item in entity_list:
            eid = item.get("id")
            if not eid:
                continue

            bio_path = f"./types/{type_name}/biographies/{eid}.json"
            if os.path.exists(bio_path):
                data = load_json_as_dict(bio_path)
                display = data.get("name", eid)
                link = f"/biography/{type_name}/{eid}"
            else:
                display = item.get("label", eid)
                link = None

            resolved.append({
                "id": eid,
                "display": display,
                "link": link,
                "confidence": item.get("confidence", None),
                "label": item.get("label", "")
            })
        return resolved

    # Process each entry and resolve all dynamic keys
    entries = []
    for raw_entry in person_data.get("entries", []):
        entry_obj = {
            "time": raw_entry.get("time", {})
        }

        # Dynamically process each type in the entry
        for key, value in raw_entry.items():
            if key == "time" or not isinstance(value, list):
                continue

            entry_obj[key] = resolve_entities(key, value)

        entries.append(entry_obj)

    return render_template(
        "person_view.html",
        person_id=person_id,
        person_name=person_name,
        entries=entries
    )


@app.route('/cancel_person_creation')
def cancel_person_creation():
    person_id = session.pop('person_id', None)
    session.pop('person_name', None)

    if person_id:
        file_path = f"./types/person/biographies/{person_id}.json"
        if os.path.exists(file_path):
            os.remove(file_path)

    return redirect('/')


def printLabel(label):
    prefix = label['label']+"="  
    if "value" in label:
        return prefix+label["value"]
    else:
        return prefix+label["category"]

#In case we want to print time in a special way
def printTime(timeLabel):
    if "value" in timeLabel:
        return timeLabel["value"]
    else:
        return timeLabel["category"]


from flask import request, redirect, flash
import os, time

@app.route('/person_biography_add', methods=['GET', 'POST'])
def person_biography_add():
    """
    Allows user to create a rich 'person biography' by selecting entries from
    people, buildings, orgs, etc. Each entry includes time, optional label and notes.
    """
    save_dir = "./types/person/biographies"
    os.makedirs(save_dir, exist_ok=True)

    if request.method == "POST":
        person_name = request.form.get("person_name", "Unnamed_Person").strip()
        entry_blocks = []
        
        index = 0
        while True:
            type_ = request.form.get(f"entry_{index}_type")
            biography = request.form.get(f"entry_{index}_biography")
            entry_idx = request.form.get(f"entry_{index}_entry")
            date = request.form.get(f"entry_{index}_date")
            label = request.form.get(f"entry_{index}_label")
            notes = request.form.get(f"entry_{index}_notes")

            if not type_:
                break

            entry_blocks.append({
                "type": type_,
                "biography": biography,
                "entry_index": int(entry_idx),
                "date": date,
                "label": label,
                "notes": notes
            })
            index += 1

        person_id = f"Person_{int(time.time())}"
        save_path = os.path.join(save_dir, f"{person_id}.json")
        save_dict_as_json(save_path, {
            "id": person_id,
            "name": person_name,
            "entries": entry_blocks
        })

        flash(f"Person biography '{person_name}' saved.", "success")
        return redirect(f"/person_biography_view/{person_id}")

    # ---- GET method ----
    # Build selector form
    html = """
    <h1>Create Person Biography</h1>
    <form method='post'>
      <label>Person Name:</label>
      <input type='text' name='person_name' required><br><br>

      <div id="entry-container">
        <!-- JS will populate multiple entry blocks here -->
      </div>

      <button type='submit'>Save Person Biography</button>
    </form>

    <script>
      let counter = 0;
      function addEntryBlock() {
        const container = document.getElementById("entry-container");
        const html = `
        <div class="entry-block">
          <h4>Entry \${counter + 1}</h4>
          Type: <input name='entry_\${counter}_type' required>
          Biography: <input name='entry_\${counter}_biography' required>
          Entry #: <input name='entry_\${counter}_entry' type='number' required>
          Date: <input name='entry_\${counter}_date'>
          Label: <input name='entry_\${counter}_label'>
          Notes: <input name='entry_\${counter}_notes'>
          <hr>
        </div>`;
        container.insertAdjacentHTML('beforeend', html);
        counter++;
      }

      // Add first block by default
      window.onload = () => addEntryBlock();

      // Add button
      const btn = document.createElement('button');
      btn.textContent = "Add Entry";
      btn.type = "button";
      btn.onclick = addEntryBlock;
      document.forms[0].insertBefore(btn, document.getElementById("entry-container").nextSibling);
    </script>
    """
    return html

@app.route('/person_biography_view/<person_id>')
def person_biography_view(person_id):
    """
    View a saved person biography made of multiple entries.
    """
    path = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(path):
        return f"<h1>Person {person_id} not found.</h1>", 404

    data = load_json_as_dict(path)
    name = data.get("name", person_id)
    entries = data.get("entries", [])

    html = f"""
    <h1>Person Biography: {name}</h1>
    <ul>
    """
    for e in entries:
        html += f"<li><strong>{e['type']}</strong> → {e['biography']} / Entry #{e['entry_index']}<br>"
        html += f"Date: {e.get('date','')} | Label: {e.get('label','')} | Notes: {e.get('notes','')}" 
        html += "</li><br>"
    html += """</ul>
    <a href='/person_biography_add'>← Back to Add</a>
    """
    return html


@app.route('/biography/<string:type_name>/<string:biography_name>')
def biography_page(type_name, biography_name):
    """
    Displays a single biography with entries, formatted times (date or subfolder), 
    subfolder-based or date-based approach, plus label images and confidence if present.
    """

    # 1. Validate the path
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return f"""
        <h1>Error: Biography Not Found</h1>
        <p>The file <code>{biography_path}</code> does not exist.</p>
        <a href='/type/{type_name}' class='back-link'>Back</a>
        """, 404

    # 2. Load the JSON data
    bio_data = load_json_as_dict(biography_path)
    display_name = bio_data.get("name", biography_name)
    readable_time = bio_data.get("readable_time", "Unknown Time")
    description = bio_data.get("description", "No description available.")
    entries = bio_data.get("entries", [])

    # 3. (Optional) Build an image dictionary for subfolder approaches & label images
    #    If you have multiple subfolder-based approach names (like "person_decade", "celebea_face_hq"), 
    #    gather them all. For brevity, we show a single scanning of `./types/<type_name>/labels/<some_subfolder>`.
    #    This is similar to what we do in 'editlabel' or 'addlabel'.
    image_dict = {}  # e.g. {"celebea_face_hq:1": "/serve_label_image/people/celebea_face_hq/1.jpg"}
    
    # Path for label definitions
    labels_base_path = f"./types/{type_name}/labels"
    if os.path.exists(labels_base_path) and os.path.isdir(labels_base_path):
        for lbl_folder in os.listdir(labels_base_path):
            # each lbl_folder might be "person_decade", "celebea_face_hq", etc.
            possible_folder = os.path.join(labels_base_path, lbl_folder)
            if os.path.isdir(possible_folder):
                # gather images
                image_files = [f for f in os.listdir(possible_folder) if f.endswith((".jpg",".png"))]
                for img in image_files:
                    base = os.path.splitext(img)[0]  # e.g. "1"
                    # store "lbl_folder:base" => serve path
                    image_key = f"{lbl_folder}:{base}"
                    image_dict[image_key] = f"/serve_label_image/{type_name}/{lbl_folder}/{img}"
            # (We ignore .json in these subfolders for this route, just images.)
    
    # # A small helper to prettify approach names (split underscores, capitalize words)
    # def prettify_name(raw: str) -> str:
    #     return " ".join(word.capitalize() for word in raw.split("_"))

    # 4. Start building the HTML
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{display_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            function removeBiography(typeName, biographyName) {{
                if (confirm("Are you sure you want to remove this biography? It will be archived.")) {{
                    fetch(`/biography_remove/${{typeName}}/${{biographyName}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Biography archived successfully.");
                                window.location.href = "/type/" + typeName;
                            }} else {{
                                alert("Error archiving biography.");
                            }}
                        }});
                }}
            }}

            function removeEntry(typeName, biographyName, entryIndex) {{
                if (confirm("Are you sure you want to remove this entry?")) {{
                    fetch(`/biography_removeentry/${{typeName}}/${{biographyName}}/${{entryIndex}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Entry removed successfully.");
                                location.reload();
                            }} else {{
                                alert("Error removing entry.");
                            }}
                        }});
                }}
            }}

            function removeLabel(typeName, biographyName, entryIndex, labelIndex) {{
                if (confirm("Are you sure you want to remove this label?")) {{
                    fetch(`/biography_removelabel/${{typeName}}/${{biographyName}}/${{entryIndex}}/${{labelIndex}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Label removed successfully.");
                                location.reload();
                            }} else {{
                                alert("Error removing label.");
                            }}
                        }});
                }}
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href="/type/{type_name}" class="back-link">Back</a>
            <h1>{display_name.capitalize()}</h1>
            <p class="timestamp">Created: {readable_time}</p>
            <p class="description">{description}</p>

            <!-- Edit or Remove biography -->
            <button class="edit-biography-button" onclick="window.location.href='/biography_edit/{type_name}/{biography_name}'">
                Edit Biography
            </button>
            <button class="delete-button" onclick="removeBiography('{type_name}', '{biography_name}')">Remove Biography</button>
            
            <h2>Entries</h2>
            <a href="/biography_addentry/{type_name}/{biography_name}" class="button add-entry-button">Add New Entry</a>

            <div class="entries-container">
    """

    # 5. Loop through each entry
    for entry_index, entry in enumerate(entries):
        time_period = entry.get("time_period", {})
        start_info = time_period.get("start", {})
        end_info   = time_period.get("end", {})

        # Format the start
        start_str, start_img_html = format_time_approach(start_info, image_dict, prettify)
        end_str, end_img_html     = format_time_approach(end_info, image_dict, prettify)

        # Now build the HTML for the entry
        entry_html = f"""
        <div class="entry">
            <p><strong>From:</strong> {start_str}</p>
            {start_img_html}
            <p><strong>To:</strong> {end_str}</p>
            {end_img_html}

            <div class="entry-actions">
                <a href="/biography_editentry/{type_name}/{biography_name}/{entry_index}" class="edit-entry-button">Edit Entry</a>
                <button class="remove-entry-button" onclick="removeEntry('{type_name}', '{biography_name}', {entry_index})">Remove Entry</button>
                <a href="/biography_addlabel/{type_name}/{biography_name}/{entry_index}" class="add-label-button">Add Label</a>
            </div>
            <h3>Labels:</h3>
            <div class="labels-container">
        """

        # Display each label
        labels_list = entry.get("labels", [])
        if labels_list:
            for label_index, label_item in enumerate(labels_list):
                lbl_name = label_item.get("label","Unknown")
                lbl_val  = label_item.get("value","Unknown")
                lbl_conf = label_item.get("confidence", None)

                # Prettify label name
                pretty_label_name = prettify(lbl_name)  # e.g. "Celebea Face Hq"
                # Build label text 
                conf_str = f"(Confidence: {lbl_conf})" if lbl_conf is not None else ""
                label_str = f"{pretty_label_name}: {lbl_val} {conf_str}"

                # Check if there's an image for this label
                # e.g. "celebea_face_hq:1"
                image_key = f"{lbl_name}:{lbl_val}"
                if image_key in image_dict and image_dict[image_key] is not None:
                    label_img = f"<img src='{image_dict[image_key]}' alt='Label Image' style='max-width:100px;'>"
                else:
                    label_img = ""

                entry_html += f"""
                <div class="label-box">
                    <span><strong>{label_str}</strong></span>
                    {label_img}
                    <div class="label-actions">
                        <a href="/biography_editlabel/{type_name}/{biography_name}/{entry_index}/{label_index}" class="edit-label-button">Edit</a>
                        <button class="remove-label-button" onclick="removeLabel('{type_name}', '{biography_name}', {entry_index}, {label_index})">Remove</button>
                    </div>
                </div>
                """
        else:
            entry_html += "<p>No labels added yet.</p>"

        entry_html += "</div></div>"  # close .labels-container, .entry
        html_template += entry_html

    html_template += """
            </div> <!-- end .entries-container -->
        </div> <!-- end .container -->
    </body>
    </html>
    """

    return html_template


def format_time_approach(time_dict, image_dict, prettify_func):
    """
    Helper function to format a single 'start' or 'end' dictionary 
    from new_entry["time_period"]["start"] or ["end"].
    Returns (text, optional_image_html).
    """
    if not time_dict:
        return ("<em>Unknown</em>", "")

    approach = time_dict.get("approach", None)
    if approach == "date":
        # partial year vs. exact date
        mode = time_dict.get("mode","exact")
        val  = time_dict.get("value","")
        is_partial = time_dict.get("is_partial", False)
        if is_partial:
            display_str = f"(Year Only) {val}"
        else:
            display_str = val if val else "<em>No date</em>"
        # no subfolder image in date approach, presumably
        return (display_str, "")
    elif approach in (None, "time"): 
        # Maybe you used the older logic or no approach?
        # We can attempt to display subfolder_type + subfolder_value
        sub_type = time_dict.get("subfolder_type","").lower()
        sub_val  = time_dict.get("subfolder_value","")
        if sub_type and sub_val:
            # Prettify name
            pretty_sub_type = prettify_func(sub_type)
            # Possibly see if there's an image
            image_key = f"{sub_type}:{sub_val}"
            if image_key in image_dict and image_dict[image_key] is not None:
                return (f"{pretty_sub_type} => {sub_val}", 
                        f"<img src='{image_dict[image_key]}' style='max-width:100px;' alt='Time Image'>")
            else:
                return (f"{pretty_sub_type} => {sub_val}", "")
        else:
            return ("<em>Unknown</em>", "")
    else:
        # approach might be e.g. "person_decade", "celebea_face_hq", etc.
        # or from your code: { 'approach': 'person_decade', 'label': 'person_decade', 'value': '1920s'}
        # We'll try to show approach + value, plus image
        approach_label = prettify_func(approach)
        val = time_dict.get("value","")
        image_key = f"{approach}:{val}"
        if image_key in image_dict and image_dict[image_key] is not None:
            return (f"{approach_label}: {val}", 
                    f"<img src='{image_dict[image_key]}' style='max-width:100px;' alt='Time Image'>")
        else:
            return (f"{approach_label}: {val}", "")



@app.route('/biography_removeentry/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['POST'])
def biography_removeentry(type_name, biography_name, entry_index):
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    asDict = load_json_as_dict(biography_path)

    # Remove entry
    try:
        del asDict["entries"][entry_index]
    except IndexError:
        return "Entry not found", 404

    # Save updated JSON
    save_dict_as_json(biography_path, asDict)

    return "Success", 200

@app.route('/biography_removelabel/<string:type_name>/<string:biography_name>/<int:entry_index>/<int:label_index>', methods=['POST'])
def biography_removelabel(type_name, biography_name, entry_index, label_index):
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"

    # Load biography data
    asDict = load_json_as_dict(biography_path)

    # Ensure the entry exists
    if entry_index >= len(asDict.get("entries", [])):
        flash("Error: Entry not found.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    entry = asDict["entries"][entry_index]

    # Ensure labels exist for this entry
    if "labels" not in entry or not entry["labels"]:
        flash("Error: No labels to remove.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # Ensure the label index is within range
    if label_index >= len(entry["labels"]):
        flash("Error: Label not found.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # Remove the label
    removed_label = entry["labels"].pop(label_index)

    # Save updated JSON
    save_dict_as_json(biography_path, asDict)

    flash(f"Label '{removed_label['label']}' removed successfully.", "success")
    return redirect(f"/biography/{type_name}/{biography_name}")



@app.route('/biography_addentry/<string:type_name>/<string:biography_name>', methods=['GET','POST'])
def biography_addentry_page(type_name, biography_name):
    """
    Displays a combined approach for adding a new entry:
      - If user chooses "date", we show exact/partial date fields for start & end.
      - If user chooses a label folder with a subfolder (e.g. 'person_decade'),
        we show subfolder-based dropdown for start & end (like 'twenties','thirties'),
        with prettified names.

    All folder names (e.g. 'person_decade') and subfolder values (e.g. 'thirties') 
    are displayed in a prettified form ('Person Decade','Thirties'). 
    However, we store the raw string in the JSON to keep consistency.

    Under the hood, if approach == 'date', no subfolder. 
    If approach == 'person_decade', we read the subfolder /types/time/labels/person_decade/*.json 
    and build a dropdown (plus a custom option).
    """

    import os, json

    # ----------- 1) Load the biography data -----------
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(json_file_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(json_file_path)
    display_name = bio_data.get("name", biography_name)
    if "entries" not in bio_data:
        bio_data["entries"] = []

    # A helper to load the subfolder-based approach
    # We'll unify them in one dictionary: { "date": { "raw":"date","pretty":"Date","has_subfolder":False,"values":[] } ... }

    # We'll define a function to prettify underscores, e.g. 'person_decade' => 'Person Decade'
    def prettify_label(s: str) -> str:
        return " ".join(part.capitalize() for part in s.split("_"))

    # ----------- 2) Build the approach dictionary -----------
    # By default, we have "date" approach => no subfolder => partial or exact date
    approach_dict = {
        "date": {
            "raw": "date",
            "pretty": "Date",
            "has_subfolder": False,
            "values": []  # no subfolder-based values
        }
    }

    # We'll also parse the /types/time/labels/ directory to find subfolder-based approaches.
    times_path = "./types/time/labels"
    if os.path.exists(times_path) and os.path.isdir(times_path):
        for file in os.listdir(times_path):
            if not file.endswith(".json"):
                continue
            folder_name = os.path.splitext(file)[0]  # e.g. 'person_decade'
            if folder_name == "date":
                # skip if there's an actual date.json, because we handle 'date' above
                continue

            subfolder_path = os.path.join(times_path, folder_name)
            if os.path.isdir(subfolder_path):
                # gather .json => sub-values
                sub_files = [f for f in os.listdir(subfolder_path) if f.endswith(".json")]
                # We'll store them as { 'raw':'thirties','pretty':'Thirties' }
                sub_values_list = []
                for sf in sub_files:
                    raw_val = os.path.splitext(sf)[0]  # e.g. 'thirties'
                    sub_values_list.append({
                        "raw": raw_val,
                        "pretty": prettify_label(raw_val)
                    })

                approach_dict[folder_name] = {
                    "raw": folder_name,  # e.g. 'person_decade'
                    "pretty": prettify_label(folder_name),  # e.g. 'Person Decade'
                    "has_subfolder": True,
                    "values": sub_values_list
                }
            else:
                # a .json with no subfolder => skip or handle differently
                pass

    # Example approach_dict might be:
    # {
    #   "date": { "raw":"date","pretty":"Date","has_subfolder":False,"values":[] },
    #   "person_decade": {
    #       "raw":"person_decade","pretty":"Person Decade","has_subfolder":True,
    #       "values":[ {"raw":"twenties","pretty":"Twenties"}, ... ]
    #   }
    # }

    # -------------- POST LOGIC --------------
    from flask import request, redirect, flash
    if request.method == 'POST':
        chosen_approach = request.form.get("start_approach","date").strip()
        if chosen_approach not in approach_dict:
            chosen_approach = "date"  # fallback

        # parse START time
        if approach_dict[chosen_approach]["has_subfolder"]:
            # subfolder approach
            start_val_raw = request.form.get("start_sub_val","").strip()
            if start_val_raw == "custom":
                start_val_raw = request.form.get("start_custom_val","").strip() or "Custom"
            start_time = {
                "approach": chosen_approach,  # e.g. 'person_decade'
                "value": start_val_raw  # store the raw string
            }
        else:
            # 'date' approach
            start_mode = request.form.get("start_date_mode","exact")
            if start_mode == "exact":
                s_date = request.form.get("start_full_date","").strip()
                if not s_date: s_date = "No Date"
                start_time = {
                    "approach": "date",
                    "mode": "exact",
                    "value": s_date,
                    "is_partial": False
                }
            else:
                s_year = request.form.get("start_partial_year","").strip()
                if not s_year: s_year = "Unknown Year"
                start_time = {
                    "approach": "date",
                    "mode": "partial",
                    "value": s_year,
                    "is_partial": True
                }

        # parse END time (same approach)
        if approach_dict[chosen_approach]["has_subfolder"]:
            end_val_raw = request.form.get("end_sub_val","").strip()
            if end_val_raw == "custom":
                end_val_raw = request.form.get("end_custom_val","").strip() or "Custom"
            end_time = {
                "approach": chosen_approach,
                "value": end_val_raw
            }
        else:
            end_mode = request.form.get("end_date_mode","exact")
            if end_mode == "exact":
                e_date = request.form.get("end_full_date","").strip()
                if not e_date: e_date = "No Date"
                end_time = {
                    "approach": "date",
                    "mode": "exact",
                    "value": e_date,
                    "is_partial": False
                }
            else:
                e_year = request.form.get("end_partial_year","").strip()
                if not e_year: e_year = "Unknown Year"
                end_time = {
                    "approach": "date",
                    "mode": "partial",
                    "value": e_year,
                    "is_partial": True
                }

        # build new entry
        new_entry = {
            "time_period": {
                "start": start_time,
                "end":   end_time
            },
            "labels": []
        }
        bio_data["entries"].append(new_entry)
        save_dict_as_json(json_file_path, bio_data)
        flash("Entry added successfully!", "success")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # -------- GET => build the form -----------
    # build an approach <option> list from approach_dict
    approach_html = ""
    for key, meta in approach_dict.items():
        # e.g. key='person_decade', meta['pretty'] = 'Person Decade'
        approach_html += f'<option value="{key}">{meta["pretty"]}</option>'

    # We'll build a JS object: { "person_decade": [ {raw:"twenties",pretty:"Twenties"}, ... ], "date":[] }
    # so we can populate start_sub_val, end_sub_val with prettified text
    subfolder_obj = {}
    for a_name, data in approach_dict.items():
        if data["has_subfolder"]:
            # data["values"] is a list of dicts like { raw:"thirties", pretty:"Thirties" }
            subfolder_obj[a_name] = data["values"]
        else:
            subfolder_obj[a_name] = []  # no subfolder

    subfolder_json = json.dumps(subfolder_obj)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Add Entry - {display_name}</title>
      <link rel="stylesheet" href="/static/styles.css">
      <script>
        let subfoldersMap = {subfolder_json};

        function onApproachChange() {{
          let approachSel = document.getElementById("start_approach").value;
          document.getElementById("end_approach").value = approachSel;

          // If this approach has subfolder => show subfolder approach
          if (subfoldersMap[approachSel] && subfoldersMap[approachSel].length > 0) {{
             document.getElementById("start_date_section").style.display = "none";
             document.getElementById("end_date_section").style.display   = "none";

             document.getElementById("start_subfolder_section").style.display = "block";
             document.getElementById("end_subfolder_section").style.display   = "block";

             // populate start_sub_val
             let startSel = document.getElementById("start_sub_val");
             startSel.innerHTML = "";
             subfoldersMap[approachSel].forEach(obj => {{
                let opt = document.createElement("option");
                opt.value = obj.raw;           // store raw in 'value'
                opt.textContent = obj.pretty;  // display prettified
                startSel.appendChild(opt);
             }});
             // add 'custom'
             let custOpt = document.createElement("option");
             custOpt.value = "custom";
             custOpt.textContent = "Enter Custom Value";
             startSel.appendChild(custOpt);

             // do same for end_sub_val
             let endSel = document.getElementById("end_sub_val");
             endSel.innerHTML = "";
             subfoldersMap[approachSel].forEach(obj => {{
                let opt = document.createElement("option");
                opt.value = obj.raw;
                opt.textContent = obj.pretty;
                endSel.appendChild(opt);
             }});
             let cust2 = document.createElement("option");
             cust2.value = "custom";
             cust2.textContent = "Enter Custom Value";
             endSel.appendChild(cust2);

          }} else {{
             // approachSel = 'date' or no subfolder => show date approach
             document.getElementById("start_subfolder_section").style.display = "none";
             document.getElementById("end_subfolder_section").style.display   = "none";

             document.getElementById("start_date_section").style.display = "block";
             document.getElementById("end_date_section").style.display   = "block";
          }}
        }}

        function toggleDateMode(prefix) {{
          let mode = document.querySelector('input[name="' + prefix + '_date_mode"]:checked').value;
          let fullDate = document.getElementById(prefix + '_full_date');
          let partialY = document.getElementById(prefix + '_partial_year');
          if (mode === "exact") {{
            fullDate.style.display = "inline-block";
            partialY.style.display = "none";
          }} else {{
            fullDate.style.display = "none";
            partialY.style.display = "inline-block";
          }}
        }}

        function checkCustomSub(prefix) {{
          let valSel = document.getElementById(prefix + '_sub_val');
          let customInput = document.getElementById(prefix + '_custom_val');
          if (valSel.value === 'custom') {{
            valSel.style.display = 'none';
            customInput.style.display = 'inline-block';
          }} else {{
            customInput.style.display = 'none';
            valSel.style.display = 'inline-block';
          }}
        }}

        window.onload = function() {{
          onApproachChange();
          toggleDateMode('start');
          toggleDateMode('end');
        }}
      </script>
    </head>

    <body>
      <div class="container">
        <a href="/biography/{type_name}/{biography_name}" class="back-link">Back</a>
        <h1>Add Entry to {display_name}</h1>

        <form method="post">
          <!-- Approach: e.g. "date" or "person_decade" -->
          <label>Approach:</label>
          <select id="start_approach" name="start_approach" onchange="onApproachChange()">
            {approach_html}
          </select>
          <input type="hidden" id="end_approach" name="end_approach" value="date">

          <hr>

          <!-- START: date approach -->
          <div id="start_date_section" style="display:none;">
            <h3>Start Date Approach</h3>
            <label>
              <input type="radio" name="start_date_mode" value="exact" checked
                     onclick="toggleDateMode('start')">
              Exact
            </label>
            <label>
              <input type="radio" name="start_date_mode" value="year"
                     onclick="toggleDateMode('start')">
              Year Only
            </label>
            <br>
            <label>Exact Start Date:</label>
            <input type="date" id="start_full_date" name="start_full_date" style="display:inline-block;">

            <label>Partial Start Year:</label>
            <input type="number" id="start_partial_year" name="start_partial_year"
                   min="1" max="9999" style="display:none;" placeholder="1952">
          </div>

          <!-- START: subfolder approach -->
          <div id="start_subfolder_section" style="display:none;">
            <h3>Start Subfolder Approach</h3>
            <label>Pick Value:</label>
            <select id="start_sub_val" name="start_sub_val" onchange="checkCustomSub('start')">
              <!-- JS populates with prettified items -->
            </select>
            <input type="text" id="start_custom_val" name="start_custom_val"
                   placeholder="Custom" style="display:none;">
          </div>

          <hr>

          <!-- END: date approach -->
          <div id="end_date_section" style="display:none;">
            <h3>End Date Approach</h3>
            <label>
              <input type="radio" name="end_date_mode" value="exact" checked
                     onclick="toggleDateMode('end')">
              Exact
            </label>
            <label>
              <input type="radio" name="end_date_mode" value="year"
                     onclick="toggleDateMode('end')">
              Year Only
            </label>
            <br>
            <label>Exact End Date:</label>
            <input type="date" id="end_full_date" name="end_full_date" style="display:inline-block;">
            <label>Partial End Year:</label>
            <input type="number" id="end_partial_year" name="end_partial_year"
                   min="1" max="9999" style="display:none;" placeholder="1980">
          </div>

          <!-- END: subfolder approach -->
          <div id="end_subfolder_section" style="display:none;">
            <h3>End Subfolder Approach</h3>
            <label>Pick Value:</label>
            <select id="end_sub_val" name="end_sub_val" onchange="checkCustomSub('end')">
              <!-- JS populates -->
            </select>
            <input type="text" id="end_custom_val" name="end_custom_val"
                   placeholder="Custom" style="display:none;">
          </div>

          <hr>
          <button type="submit">Add Entry</button>
        </form>
      </div>
    </body>
    </html>
    """




@app.route('/biography_addentry_submit/<string:type_name>/<string:biography_name>', methods=['POST'])
def biography_addentry_submit(type_name, biography_name):
    """
    POST to create a new entry. Checks if user picked 'date' or 'person_decade'.
    If 'date', parse exact/partial date fields.
    If 'person_decade', parse subfolder fields.
    """
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(json_file_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(json_file_path)
    if "entries" not in bio_data:
        bio_data["entries"] = []

    # 1. Grab approach for start & end
    start_approach = request.form.get("start_approach", "date")   # e.g. 'date' or 'person_decade'
    end_approach   = request.form.get("end_approach", "date")

    # We'll build a dictionary for start_time, end_time

    # -------- START --------
    if start_approach == "date":
        # parse radio => exact or year
        start_date_mode = request.form.get("start_date_mode", "exact")
        if start_date_mode == "exact":
            start_date_val = request.form.get("start_full_date", "").strip()  # "2025-03-25"
            start_is_partial = False
        else:
            start_date_val = request.form.get("start_partial_year", "").strip()  # e.g. "1952"
            start_is_partial = True

        start_data = {
            "approach": "date",
            "mode": start_date_mode,
            "value": start_date_val,
            "is_partial": start_is_partial
        }

    else:
        # approach = 'person_decade' or any subfolder-based
        start_label = request.form.get("start_time_label", "").strip()
        start_value = request.form.get("start_time_value", "").strip()
        if start_value == "custom":
            start_custom = request.form.get("start_custom_time_value", "").strip()
            if start_custom:
                start_value = start_custom

        start_data = {
            "approach": "person_decade",  # or subfolder approach
            "label": start_label,
            "value": start_value
        }

    # -------- END --------
    if end_approach == "date":
        end_date_mode = request.form.get("end_date_mode", "exact")
        if end_date_mode == "exact":
            end_date_val = request.form.get("end_full_date", "").strip()
            end_is_partial = False
        else:
            end_date_val = request.form.get("end_partial_year", "").strip()
            end_is_partial = True

        end_data = {
            "approach": "date",
            "mode": end_date_mode,
            "value": end_date_val,
            "is_partial": end_is_partial
        }
    else:
        end_label = request.form.get("end_time_label", "").strip()
        end_value = request.form.get("end_time_value", "").strip()
        if end_value == "custom":
            end_custom = request.form.get("end_custom_time_value", "").strip()
            if end_custom:
                end_value = end_custom

        end_data = {
            "approach": "person_decade",
            "label": end_label,
            "value": end_value
        }

    # 2. Build the new entry
    new_entry = {
        "time_period": {
            "start": start_data,
            "end": end_data
        },
        "labels": []
    }

    # 3. Save
    bio_data["entries"].append(new_entry)
    save_dict_as_json(json_file_path, bio_data)

    flash("Entry added successfully!", "success")
    return redirect(f"/biography/{type_name}/{biography_name}")



@app.route('/biography_editentry/<string:type_name>/<string:biography_name>/<int:entry_index>')
def biography_editentry_page(type_name, biography_name, entry_index):
    """
    A fully updated Edit Entry route that:
      1) Lets the user pick 'date' approach or a subfolder approach (e.g. 'person_decade').
      2) If 'date' is chosen, user must pick 'exact' or 'partial' for start/end.
         - 'exact' => <input type="date">
         - 'partial' => a <select> of years 1900..2100, with type-ahead logic.
      3) Ensures End date/year >= Start date/year if both are 'date' approach.
      4) Hides partial-year field when 'exact' is selected, hides exact-date field if 'partial' is selected.
      5) Syncs approach: changing Start approach => End approach is forced to match.
         Similarly, if user picks Start 'exact' => End is forced 'exact', etc.
    """

    import os, json

    # 1) Load the biography & specific entry
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    # Helper to load JSON
    def load_json_as_dict(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    bio_data = load_json_as_dict(biography_path)
    entries_list = bio_data.get("entries", [])
    if entry_index >= len(entries_list):
        return "<h1>Error: Entry Index Out of Range</h1>", 404

    entry = entries_list[entry_index]
    time_period = entry.setdefault("time_period", {})
    start_block = time_period.setdefault("start", {})
    end_block   = time_period.setdefault("end",   {})

    # 2) We'll define a dictionary of possible approaches:
    #    "date" => no subfolder, plus any subfolders in /types/time/labels/<folder_name>
    times_path = f"./types/time/labels"
    approach_dict = {
        "date": {
            "raw": "date",
            "pretty": "Date",
            "has_subfolder": False,
            "values": []
        }
    }

    def prettify_label(s):
        return " ".join(part.capitalize() for part in s.split("_"))

    # If there's a 'person_decade' or other subfolder, include it
    if os.path.exists(times_path) and os.path.isdir(times_path):
        for file in os.listdir(times_path):
            if file.endswith(".json"):
                folder_name = os.path.splitext(file)[0]
                if folder_name == "date":
                    continue  # skip if there's date.json
                subfolder_dir = os.path.join(times_path, folder_name)
                if os.path.isdir(subfolder_dir):
                    # gather sub-values
                    sub_vals_list = []
                    for sf in os.listdir(subfolder_dir):
                        if sf.endswith(".json"):
                            raw_val = os.path.splitext(sf)[0]
                            sub_vals_list.append({
                                "raw": raw_val,
                                "pretty": prettify_label(raw_val)
                            })
                    approach_dict[folder_name] = {
                        "raw": folder_name,
                        "pretty": prettify_label(folder_name),
                        "has_subfolder": True,
                        "values": sub_vals_list
                    }

    # 3) Extract the user's existing approach & data
    start_approach = start_block.get("approach","date")  # e.g. 'date' or 'person_decade'
    start_mode     = start_block.get("mode","exact") if start_approach=="date" else ""
    start_value    = start_block.get("value","")

    end_approach = end_block.get("approach","date")
    end_mode     = end_block.get("mode","exact") if end_approach=="date" else ""
    end_value    = end_block.get("value","")

    # 4) Build a subfolder map for JS
    approach_obj = {}
    for a_key, meta in approach_dict.items():
        if meta["has_subfolder"]:
            approach_obj[a_key] = meta["values"]
        else:
            approach_obj[a_key] = []

    approach_obj_json = json.dumps(approach_obj)

    def build_approach_options(selected):
        # e.g. <option value="date" selected>Date</option>
        out = []
        for key, data in approach_dict.items():
            sel = "selected" if key == selected else ""
            out.append(f'<option value="{key}" {sel}>{data["pretty"]}</option>')
        return "".join(out)

    start_approach_options = build_approach_options(start_approach)
    end_approach_options   = build_approach_options(end_approach)

    # 5) Return the HTML with all logic
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Edit Entry - {bio_data.get("name", biography_name)}</title>
      <link rel="stylesheet" href="/static/styles.css">
      <style>
        .hidden {{ display: none; }}
      </style>
      <script>
        let approachData = {approach_obj_json};

        // build year list 1900..2100
        function buildYearOptions(selectEl, minYear=1900) {{
          selectEl.innerHTML = "";
          for (let y = minYear; y <= 2100; y++) {{
            let opt = document.createElement("option");
            opt.value = ""+y;
            opt.textContent = ""+y;
            selectEl.appendChild(opt);
          }}
        }}

        // attach a type-ahead so user can type e.g. 1 9 5 2 => jump to 1952
        function attachTypeAhead(selectEl) {{
          let typed = "";
          let lastTime = 0;

          selectEl.addEventListener("keydown", function(e) {{
            let now = Date.now();
            if (now - lastTime > 800) {{
              typed = "";
            }}
            lastTime = now;

            if (e.key === "Backspace") {{
              typed = typed.slice(0,-1);
              e.preventDefault();
            }} else if (/\\d/.test(e.key)) {{
              typed += e.key;
              e.preventDefault();
            }} else {{
              return;
            }}

            for (let i=0; i<selectEl.options.length; i++) {{
              if (selectEl.options[i].value.startsWith(typed)) {{
                selectEl.selectedIndex = i;
                break;
              }}
            }}
          }});
        }}

        function onApproachChange(prefix) {{
          // 1) first update the block for 'prefix'
          let approachSel = document.getElementById(prefix + '_approach').value;
          let dateSec = document.getElementById(prefix + '_date_section');
          let subfSec = document.getElementById(prefix + '_subfolder_section');

          if (approachData[approachSel] && approachData[approachSel].length > 0) {{
            // subfolder approach
            dateSec.classList.add("hidden");
            subfSec.classList.remove("hidden");

            let dd = document.getElementById(prefix + '_sub_val');
            dd.innerHTML = "";
            approachData[approachSel].forEach(obj => {{
              let opt = document.createElement("option");
              opt.value = obj.raw;
              opt.textContent = obj.pretty;
              dd.appendChild(opt);
            }});
            let customOpt = document.createElement("option");
            customOpt.value = "custom";
            customOpt.textContent = "Enter Custom Value";
            dd.appendChild(customOpt);

          }} else {{
            // date approach
            subfSec.classList.add("hidden");
            dateSec.classList.remove("hidden");
          }}

          // 2) If prefix='start', force end approach to match
          if (prefix === 'start') {{
            document.getElementById('end_approach').value = approachSel;
            onApproachChange('end');
          }}

          // enforce constraints after approach changes
          enforceEndConstraints();
        }}

        function onToggleDateMode(prefix) {{
          let exactRadio   = document.getElementById(prefix + '_date_mode_exact');
          let partialRadio = document.getElementById(prefix + '_date_mode_partial');
          let exactDiv     = document.getElementById(prefix + '_exactDiv');
          let partialDiv   = document.getElementById(prefix + '_partialDiv');

          if (exactRadio.checked) {{
            exactDiv.classList.remove("hidden");
            partialDiv.classList.add("hidden");
          }} else if (partialRadio.checked) {{
            exactDiv.classList.add("hidden");
            partialDiv.classList.remove("hidden");
            // build year list if empty
            let sel = document.getElementById(prefix + '_partial_year_select');
            if (sel.options.length < 1) {{
              buildYearOptions(sel, 1900);
              attachTypeAhead(sel);
            }}
          }}

          // If user toggles start partial/exact => do same for end
          if (prefix==='start') {{
            if (exactRadio.checked) {{
              document.getElementById('end_date_mode_exact').checked = true;
            }} else {{
              document.getElementById('end_date_mode_partial').checked = true;
            }}
            onToggleDateMode('end');
          }}

          enforceEndConstraints();
        }}

        // ensure end≥start if approach='date'
        function enforceEndConstraints() {{
          let sAp = document.getElementById('start_approach').value;
          let eAp = document.getElementById('end_approach').value;

          if (sAp !== 'date' || eAp !== 'date') {{
            // subfolder => no constraints
            return;
          }}

          let sExact = document.getElementById('start_date_mode_exact').checked;
          let eExact = document.getElementById('end_date_mode_exact').checked;

          if (sExact) {{
            let sVal = document.getElementById('start_full_date').value;
            if (!sVal) return; // can't do anything if no start date
            if (eExact) {{
              document.getElementById('end_full_date').min = sVal;
            }} else {{
              // end partial
              let year = parseInt(sVal.split('-')[0])||1900;
              let endSel = document.getElementById('end_partial_year_select');
              rebuildYearDropdown(endSel, year);
            }}
          }} else {{
            // start partial
            let sYear = parseInt(document.getElementById('start_partial_year_select').value)||1900;
            if (eExact) {{
              document.getElementById('end_full_date').min = sYear + '-01-01';
            }} else {{
              // partial => partial
              let eSel = document.getElementById('end_partial_year_select');
              rebuildYearDropdown(eSel, sYear);
            }}
          }}
        }}

        function rebuildYearDropdown(selEl, startYear) {{
          selEl.innerHTML = "";
          for (let y = startYear; y<=2100; y++) {{
            let opt = document.createElement('option');
            opt.value = ""+y;
            opt.textContent = ""+y;
            selEl.appendChild(opt);
          }}
        }}

        function checkCustom(prefix) {{
          let dd = document.getElementById(prefix + '_sub_val');
          let cust = document.getElementById(prefix + '_custom_val');
          if (dd.value==='custom') {{
            dd.style.display='none';
            cust.style.display='inline-block';
          }} else {{
            cust.style.display='none';
            dd.style.display='inline-block';
          }}
        }}

        window.onload = function() {{
          // 1) We run onApproachChange('start') => sets start approach, updates end approach => onApproachChange('end')
          onApproachChange('start');
          // 2) Then set the date mode toggles
          onToggleDateMode('start');
          onToggleDateMode('end');
          // 3) Possibly fill partial year or date from old data in a DOMContentLoaded snippet
          //    Then call enforceEndConstraints() again
          enforceEndConstraints();
        }};
      </script>
    </head>
    <body>
      <div class="container">
        <a href="/biography/{type_name}/{biography_name}" class="back-link">Back</a>
        <h1>Edit Entry for {bio_data.get("name", biography_name)}</h1>

        <!-- We'll assume your POST route is /biography_editentry_submit/... -->
        <form action="/biography_editentry_submit/{type_name}/{biography_name}/{entry_index}" method="post">

          <!-- START BLOCK -->
          <h2>Start Time</h2>
          <label>Approach:</label>
          <select id="start_approach" name="start_approach" onchange="onApproachChange('start')">
            {start_approach_options}
          </select>

          <div id="start_date_section" class="">
            <label>
              <input type="radio" id="start_date_mode_exact" name="start_date_mode" value="exact"
                     onclick="onToggleDateMode('start')"> Exact
            </label>
            <label>
              <input type="radio" id="start_date_mode_partial" name="start_date_mode" value="partial"
                     onclick="onToggleDateMode('start')"> Partial
            </label>
            <br><br>

            <!-- EXACT sub-block -->
            <div id="start_exactDiv">
              <label>Exact Start Date:</label>
              <input type="date" id="start_full_date" name="start_full_date">
            </div>

            <!-- PARTIAL sub-block -->
            <div id="start_partialDiv" class="hidden">
              <label>Partial Start Year:</label>
              <select id="start_partial_year_select" name="start_partial_year_select"></select>
            </div>
          </div>

          <div id="start_subfolder_section" class="hidden">
            <label>Pick Value:</label>
            <select id="start_sub_val" name="start_sub_val" onchange="checkCustom('start')"></select>
            <input type="text" id="start_custom_val" name="start_custom_val" placeholder="Custom" class="hidden">
          </div>

          <hr>

          <!-- END BLOCK -->
          <h2>End Time</h2>
          <label>Approach:</label>
          <select id="end_approach" name="end_approach" onchange="onApproachChange('end')">
            {end_approach_options}
          </select>

          <div id="end_date_section" class="hidden">
            <label>
              <input type="radio" id="end_date_mode_exact" name="end_date_mode" value="exact"
                     onclick="onToggleDateMode('end')"> Exact
            </label>
            <label>
              <input type="radio" id="end_date_mode_partial" name="end_date_mode" value="partial"
                     onclick="onToggleDateMode('end')"> Partial
            </label>
            <br><br>

            <div id="end_exactDiv">
              <label>Exact End Date:</label>
              <input type="date" id="end_full_date" name="end_full_date">
            </div>

            <div id="end_partialDiv" class="hidden">
              <label>Partial End Year:</label>
              <select id="end_partial_year_select" name="end_partial_year_select"></select>
            </div>
          </div>

          <div id="end_subfolder_section" class="hidden">
            <label>Pick Value:</label>
            <select id="end_sub_val" name="end_sub_val" onchange="checkCustom('end')"></select>
            <input type="text" id="end_custom_val" name="end_custom_val" placeholder="Custom" class="hidden">
          </div>

          <hr>
          <button type="submit">Save Changes</button>
        </form>

        <!-- If you need to fill old data e.g. partial year or subfolder:
             We'll do that after the DOM loads, then enforce constraints again. -->
        <script>
          document.addEventListener('DOMContentLoaded', function() {{
            // e.g. if your stored 'start_mode' == 'partial', do:
            //   document.getElementById('start_date_mode_partial').checked = true;
            //   onToggleDateMode('start');
            //   document.getElementById('start_partial_year_select').value = '{start_value}';
            // same for end
            // Then run enforceEndConstraints() again
          }});
        </script>
      </div>
    </body>
    </html>
    """

    return html




@app.route('/biography_editentry_submit/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['POST'])
def biography_editentry_submit(type_name, biography_name, entry_index):
    """
    POST route that saves user changes from the updated editentry page:
      - If start_approach == 'date', parse start_date_mode = 'exact' or 'partial', plus the relevant field.
      - If subfolder approach, parse start_sub_val or custom typed.
      - Same logic for end_approach => end_date_mode or subfolder.
    Then we store them in time_period["start"] and time_period["end"].
    """

    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(json_file_path):
        return "<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(json_file_path)
    entries = bio_data.get("entries", [])
    if entry_index >= len(entries):
        return "<h1>Error: Entry Not Found</h1>", 404

    entry = entries[entry_index]
    if "time_period" not in entry:
        entry["time_period"] = {}
    time_period = entry["time_period"]
    if "start" not in time_period:
        time_period["start"] = {}
    if "end" not in time_period:
        time_period["end"] = {}

    # ------------------ PARSE START BLOCK ------------------
    start_approach = request.form.get("start_approach","date").strip()  # e.g. 'date' or 'person_decade'
    if start_approach == "date":
        start_date_mode = request.form.get("start_date_mode","exact").strip()  # 'exact' or 'partial'
        if start_date_mode == "exact":
            # read <input type="date" id="start_full_date">
            s_val = request.form.get("start_full_date","").strip()
            if not s_val:
                s_val = "No Date"
            time_period["start"] = {
                "approach": "date",
                "mode": "exact",
                "value": s_val,
                "is_partial": False
            }
        else:
            # partial => read <select name="start_partial_year_select">
            s_val = request.form.get("start_partial_year_select","").strip()
            if not s_val:
                s_val = "Unknown Year"
            time_period["start"] = {
                "approach": "date",
                "mode": "partial",
                "value": s_val,
                "is_partial": True
            }
    else:
        # subfolder approach
        # e.g. start_sub_val = "thirties" or "custom"
        s_sub_val = request.form.get("start_sub_val","").strip()
        if s_sub_val == "custom":
            s_sub_val = request.form.get("start_custom_val","").strip() or "Custom"
        time_period["start"] = {
            "approach": start_approach,
            "value": s_sub_val
        }

    # ------------------ PARSE END BLOCK ------------------
    end_approach = request.form.get("end_approach","date").strip()
    if end_approach == "date":
        end_date_mode = request.form.get("end_date_mode","exact").strip()
        if end_date_mode == "exact":
            e_val = request.form.get("end_full_date","").strip()
            if not e_val:
                e_val = "No Date"
            time_period["end"] = {
                "approach": "date",
                "mode": "exact",
                "value": e_val,
                "is_partial": False
            }
        else:
            # partial
            e_val = request.form.get("end_partial_year_select","").strip()
            if not e_val:
                e_val = "Unknown Year"
            time_period["end"] = {
                "approach": "date",
                "mode": "partial",
                "value": e_val,
                "is_partial": True
            }
    else:
        # subfolder approach
        e_sub_val = request.form.get("end_sub_val","").strip()
        if e_sub_val == "custom":
            e_sub_val = request.form.get("end_custom_val","").strip() or "Custom"
        time_period["end"] = {
            "approach": end_approach,
            "value": e_sub_val
        }

    # ------------------ Save JSON & Redirect ------------------
    entry["time_period"] = time_period
    save_dict_as_json(json_file_path, bio_data)

    return redirect(f"/biography/{type_name}/{biography_name}")


@app.route('/type/<string:type_name>')
def type_page(type_name):
    """
    Displays the type page for biographies:
    - Search bar for partial matches by name or label values.
    - Live checkboxes that filter by label name.
    - View-only mode: no add/edit/delete options.
    - Link to label viewer.
    """

    type_metadata_path = f"./types/{type_name}.json"
    if not os.path.exists(type_metadata_path):
        return f"""
        <h1>Error: Type metadata not found</h1>
        <p>The file <code>{type_metadata_path}</code> does not exist.</p>
        """, 404
    type_meta = load_json_as_dict(type_metadata_path)

    biographies_path = f"./types/{type_name}/biographies"
    biography_list = []
    all_label_names = set()

    if os.path.exists(biographies_path):
        for file in os.listdir(biographies_path):
            if file.endswith(".json"):
                file_path = os.path.join(biographies_path, file)
                bio_data = load_json_as_dict(file_path)

                name = bio_data.get("name", "Unknown")
                label_names_in_this_bio = set()
                label_values_in_this_bio = []

                for entry in bio_data.get("entries", []):
                    for lbl in entry.get("labels", []):
                        if lbl["label"].lower() in ["time", "start", "end"]:
                            continue
                        label_name = lbl["label"].strip().lower()
                        label_value = lbl.get("value", "").strip().lower()
                        label_names_in_this_bio.add(label_name)
                        if label_value:
                            label_values_in_this_bio.append(label_value)

                all_label_names.update(label_names_in_this_bio)
                bio_label_names_str = ",".join(sorted(label_names_in_this_bio))
                bio_label_values_str = ",".join(label_values_in_this_bio)

                biography_list.append({
                    "file_basename": file[:-5],
                    "name": name.capitalize(),
                    "label_names_str": bio_label_names_str,
                    "label_values_str": bio_label_values_str
                })

    def prettify_label_name(raw_name):
        return " ".join(word.capitalize() for word in raw_name.split("_"))

    sorted_label_names = sorted(all_label_names)
    label_options_html = ""
    for lbl_name in sorted_label_names:
        display_name = prettify_label_name(lbl_name)
        label_options_html += f"""
        <label class='filter-label'>
            <input type='checkbox' value='{lbl_name}' class='filter-checkbox'> {display_name}
        </label>
        """

    biography_items_html = ""
    for bio in biography_list:
        biography_items_html += f"""
        <div class='biography-item'
             data-name='{bio["name"].lower()}'
             data-labelnames='{bio["label_names_str"]}'
             data-labelvalues='{bio["label_values_str"]}'>
            <a href="/biography/{type_name}/{bio['file_basename']}" class='biography-button'>
                <strong>{bio['name']}</strong>
            </a>
        </div>
        """

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset='UTF-8' />
        <title>{type_name.capitalize()}</title>
        <link rel='stylesheet' href='/static/styles.css'>
    </head>
    <body>
        <div class='container'>
            <a href='/' class='back-link'>← Back</a>
            <h1>{type_name.capitalize()}</h1>
            <p class='description'>{type_meta.get("description", "No description available.")}</p>

            <div class='search-container'>
                <input type='text' id='searchBar' class='search-input' placeholder='Search by name or label value...'>
                <button id='resetSearch' class='reset-button'>Reset Search</button>
            </div>

            <div class='filter-container'>
                <label>Filter by Label Name:</label>
                <div class='filter-labels'>
                    {label_options_html}
                </div>
            </div>

            <h2>Biographies</h2>
            <div class='biography-container' id='biographyList'>
                {biography_items_html if biography_items_html else "<p class='no-data'>No biographies found.</p>"}
            </div>

            <div class="label-explorer-link">
                <a href="/view_labels/{type_name}" class="view-labels-button">View All Labels</a>
            </div>
        </div>

        <script>
            const searchBar = document.getElementById('searchBar');
            const resetButton = document.getElementById('resetSearch');
            const checkboxes = document.querySelectorAll('.filter-checkbox');
            const biographyItems = document.querySelectorAll('.biography-item');

            function applyFilters() {{
                const query = searchBar.value.toLowerCase().trim();
                const selectedLabelNames = Array.from(checkboxes)
                    .filter(ch => ch.checked)
                    .map(ch => ch.value.toLowerCase());

                biographyItems.forEach(item => {{
                    const bioName = item.dataset.name;
                    const labelNames = item.dataset.labelnames;
                    const labelValues = item.dataset.labelvalues;

                    let searchMatch = true;
                    if (query) {{
                        const nameMatch = bioName.includes(query);
                        const valueMatch = labelValues.includes(query);
                        searchMatch = (nameMatch || valueMatch);
                    }}

                    let labelNameMatch = true;
                    if (selectedLabelNames.length > 0) {{
                        const labelNamesArr = labelNames.split(",");
                        labelNameMatch = selectedLabelNames.every(lbl => labelNamesArr.includes(lbl));
                    }}

                    const shouldShow = (searchMatch && labelNameMatch);
                    item.style.display = shouldShow ? 'block' : 'none';
                }});
            }}

            searchBar.addEventListener('input', applyFilters);
            checkboxes.forEach(ch => ch.addEventListener('change', applyFilters));

            resetButton.addEventListener('click', () => {{
                searchBar.value = "";
                checkboxes.forEach(ch => (ch.checked = false));
                biographyItems.forEach(item => item.style.display = 'block');
            }});
        </script>
    </body>
    </html>
    """

    return html_template


@app.route('/view_labels/<string:type_name>')
def view_labels(type_name):
    import os
    import json

    labels_dir = f'./types/{type_name}/labels'
    if not os.path.exists(labels_dir):
        return f"<h1>Error: Label folder not found for {type_name}</h1>", 404

    label_types = []
    for entry in sorted(os.listdir(labels_dir)):
        full_path = os.path.join(labels_dir, entry)
        if os.path.isdir(full_path):
            images_and_metadata = []
            for f in os.listdir(full_path):
                if f.endswith('.json'):
                    json_path = os.path.join(full_path, f)
                    
                    # Prefer .jpg, fallback to .png
                    image_filename = f.replace('.json', '.jpg')
                    image_full_path = os.path.join(full_path, image_filename)
                    if not os.path.exists(image_full_path):
                        image_filename = f.replace('.json', '.png')
                        image_full_path = os.path.join(full_path, image_filename)
                    
                    # Construct image URL if it exists
                    image_url = f"/types/{type_name}/labels/{entry}/{image_filename}" if os.path.exists(image_full_path) else None
                    
                    with open(json_path, 'r') as jf:
                        try:
                            data = json.load(jf)
                            description = data.get("description", "")
                            properties = data.get("properties", {})

                            properties_list = []
                            for key, val in properties.items():
                                if isinstance(val, dict):
                                    properties_list.append((prettify(key), val.get("value", "")))

                            # Add JSON filename (without extension) to search text and display
                            file_display_name = prettify(f.replace('.json', ''))

                            search_text = " ".join([
                                file_display_name
                            ] + [
                                str(val.get("value", "")) for val in properties.values()
                                if isinstance(val, dict)
                            ]).lower()

                            images_and_metadata.append({
                                "file": file_display_name,
                                "img": image_url,
                                "description": description,
                                "properties_list": properties_list,
                                "search_text": search_text
                            })
                        except Exception:
                            continue

            label_types.append({
                "name": entry,
                "display_name": prettify(entry),
                "description": get_label_description(labels_dir, entry),
                "values": images_and_metadata
            })

    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>View Labels</title>
        <link rel="stylesheet" href="/static/styles.css">
        <style>
            .label-img { max-width: 120px; display: block; margin: 4px 0; }
            .label-group { margin-bottom: 30px; }
            .label-values { display: flex; flex-wrap: wrap; gap: 20px; margin-top: 10px; }
            .label-box { border: 1px solid #ccc; padding: 8px; width: 150px; }
            .label-description { font-style: italic; font-size: 0.9em; margin-bottom: 5px; }
            .search-input { padding: 8px; width: 300px; margin-bottom: 20px; font-size: 1em; }
            .back-link { margin-bottom: 20px; display: inline-block; text-decoration: none; font-size: 1.1em; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/type/{{ type_name }}" class="back-link">← Back</a>
            <h1>View Labels for {{ type_name.capitalize() }}</h1>
            <input type="text" id="labelSearch" class="search-input" placeholder="Search label values...">

            {% for lbl in label_types %}
            <div class="label-group">
                <h2>{{ lbl.display_name }}</h2>
                {% if lbl.description %}
                <p class="label-description">{{ lbl.description }}</p>
                {% endif %}
                <div class="label-values">
                    {% for item in lbl["values"] %}
                    <div class="label-box" data-search="{{ item.search_text }}">
                        {% if item.img %}
                        <img src="{{ item.img }}" alt="Label Image" class="label-img">
                        {% endif %}
                        <strong>Name</strong>: {{ item.file }}<br>
                        {% for pair in item["properties_list"] %}
                            <strong>{{ pair[0] }}</strong>: {{ pair[1] }}<br>
                        {% endfor %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </div>

        <script>
            const input = document.getElementById('labelSearch');
            input.addEventListener('input', () => {
                const val = input.value.toLowerCase();
                document.querySelectorAll('.label-box').forEach(box => {
                    const text = box.dataset.search;
                    box.style.display = text.includes(val) ? 'block' : 'none';
                });
            });
        </script>
    </body>
    </html>
    '''

    return render_template_string(html_template, type_name=type_name, label_types=label_types)


@app.route('/search/<string:type_name>')
def search_biographies(type_name):
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])

    biographies_path = f"./types/{type_name}/biographies"
    if not os.path.exists(biographies_path):
        return jsonify([])

    results = []
    for file in os.listdir(biographies_path):
        if file.endswith(".json"):
            bio_data = load_json_as_dict(os.path.join(biographies_path, file))
            biography_name = file[:-5]  # Remove ".json"
            display_name = bio_data.get("name", biography_name)

            # Search through labels
            for entry in bio_data.get("entries", []):
                for label in entry.get("labels", []):
                    label_value = str(label.get("value", "")).lower()
                    label_name = str(label.get("label", "")).lower()

                    if query in label_value or query in label_name:
                        results.append({
                            "name": biography_name,
                            "display_name": display_name,
                            "matched_label": f"{label_name}: {label_value}"
                        })
                        break  # Stop searching further in this biography

    return jsonify(results)


from flask import send_from_directory

@app.route('/serve_label_image/<string:type_name>/<string:label_name>/<string:image_name>')
def serve_label_image(type_name, label_name, image_name):
    """ Serve images from the `types` directory dynamically. """
    image_path = f"./types/{type_name}/labels/{label_name}/"  # Adjust if the structure is different
    return send_from_directory(image_path, image_name)




@app.route('/biography_addlabel/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['GET'])
def biography_addlabel_page(type_name, biography_name, entry_index):
    """
    Displays the Add Label form with:
      - A prettified label name dropdown (e.g. "celebea_face_hq" => "Celebea Face Hq").
      - Subfolder-based values, plus custom typed value.
      - Image preview if <folder>:<value>.jpg exists.
    """

    # 1. Load the biography & entry
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    bio_data = load_json_as_dict(json_file_path)

    if entry_index >= len(bio_data.get("entries", [])):
        return f"<h1>Error: Entry Not Found</h1>", 404

    entry = bio_data["entries"][entry_index]
    display_name = bio_data.get("name", biography_name)

    # 2. Gather all label folders in ./types/<type_name>/labels/
    labels_path = f"./types/{type_name}/labels"
    label_folders = [f for f in os.listdir(labels_path) if f.endswith(".json")]
    # We'll store "folder_name => { 'values': [...], 'images': {...} }"
    label_info_dict = {}

    def prettify_label_name(raw: str) -> str:
        return " ".join(word.capitalize() for word in raw.split("_"))

    for label_file in label_folders:
        lbl_name = os.path.splitext(label_file)[0]  # e.g. "celebea_face_hq"
        label_folder_path = os.path.join(labels_path, lbl_name)
        label_json_path   = os.path.join(labels_path, label_file)

        # Load label data
        label_json = load_json_as_dict(label_json_path)
        values_list = label_json.get("values", [])
        
        images_map = {}  # e.g. {"1": "/serve_label_image/.../1.jpg"}

        # If subfolder has .json or images
        if os.path.exists(label_folder_path) and os.path.isdir(label_folder_path):
            subfolder_files = [sf for sf in os.listdir(label_folder_path) if sf.endswith(".json")]
            sub_values = [os.path.splitext(sf)[0] for sf in subfolder_files]
            # unify the two sets
            combined_values = list(set(values_list + sub_values))
            # find images
            image_files = [img for img in os.listdir(label_folder_path) if img.endswith((".jpg",".png"))]
            for val in combined_values:
                matched_img = next((img for img in image_files if os.path.splitext(img)[0] == val), None)
                if matched_img:
                    images_map[val] = f"/serve_label_image/{type_name}/{lbl_name}/{matched_img}"
                else:
                    images_map[val] = None
        else:
            combined_values = values_list

        label_info_dict[lbl_name] = {
            "pretty_name": prettify_label_name(lbl_name),
            "values": combined_values,
            "images": images_map
        }

    # 3. Convert to JSON for the front-end JS
    label_info_json = json.dumps(label_info_dict)

    # 4. Build HTML
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Add Label to {display_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">

        <script>
            let labelInfo = {label_info_json};

            function prettifyLabelName(raw) {{
                // We can do the same in JS if needed, or rely on your Python logic
                let parts = raw.split("_");
                return parts.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
            }}

            function updateLabelDetails() {{
                let lblSelect = document.getElementById("label_type");
                let selected = lblSelect.value; // e.g. "celebea_face_hq"

                let descContainer = document.getElementById("label_description");
                let valSelect     = document.getElementById("label_value");
                let customInput   = document.getElementById("custom_label_value");
                let imgContainer  = document.getElementById("label_image");
                let placeholder   = document.getElementById("image_placeholder");

                // Reset
                valSelect.innerHTML = "";
                customInput.style.display = "none";
                customInput.value = "";
                customInput.required = false;

                // Fill value dropdown
                if (labelInfo[selected]) {{
                    let vals = labelInfo[selected].values;
                    vals.forEach(v => {{
                        let opt = document.createElement("option");
                        opt.value = v;
                        opt.textContent = v;
                        valSelect.appendChild(opt);
                    }});
                    // add 'custom' option
                    let customOpt = document.createElement("option");
                    customOpt.value = "custom";
                    customOpt.textContent = "Enter Custom Value";
                    valSelect.appendChild(customOpt);
                }}

                // Clear images initially
                imgContainer.style.display = "none";
                placeholder.style.display  = "none";

                // We'll call checkCustomValue afterwards 
                // so the user can see if it's custom or not
            }}

            function checkCustomValue() {{
                let valSelect = document.getElementById("label_value");
                let customInput = document.getElementById("custom_label_value");
                let selectedLbl = document.getElementById("label_type").value;

                let imgContainer = document.getElementById("label_image");
                let placeholder  = document.getElementById("image_placeholder");

                if (valSelect.value === "custom") {{
                    valSelect.style.display = "none";
                    customInput.style.display = "block";
                    customInput.required = true;
                    // no specific image for custom unless we guess
                    imgContainer.style.display = "none";
                    placeholder.style.display  = "block";
                    placeholder.innerHTML      = "No image for custom value";
                }} else {{
                    customInput.style.display = "none";
                    customInput.required = false;
                    valSelect.style.display = "inline-block";

                    // Possibly show an image if labelInfo has images
                    let chosenVal = valSelect.value;
                    let imagesMap = labelInfo[selectedLbl].images || {{}};
                    if (imagesMap[chosenVal]) {{
                        imgContainer.src = imagesMap[chosenVal];
                        imgContainer.style.display = "block";
                        placeholder.style.display = "none";
                    }} else {{
                        placeholder.innerHTML = "Expected Image: " + chosenVal + ".jpg or .png";
                        placeholder.style.display = "block";
                        imgContainer.style.display = "none";
                    }}
                }}
            }}

            window.onload = function() {{
                updateLabelDetails();
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href='/biography/{type_name}/{biography_name}' class="back-link">Back</a>
            <h1>Add Label to {display_name.capitalize()}</h1>

            <div class="label-container">
                <p><strong>From:</strong> {printTime(entry["time_period"]["start"])}</p>
                <p><strong>To:</strong> {printTime(entry["time_period"]["end"])}</p>

                <form action='/biography_addlabel_submit/{type_name}/{biography_name}/{entry_index}' method='post'>
                    <label for='label_type'>Choose a label folder:</label>
                    <select name='label_type' id='label_type' onchange="updateLabelDetails()" required>
                        <option value="">Select a folder</option>
    """

    # 5. Build the <option> list for label_type, using prettified name
    for folder_name, info in label_info_dict.items():
        pretty_name = info["pretty_name"]
        html_template += f"<option value='{folder_name}'>{pretty_name}</option>"

    html_template += """
                    </select>

                    <p id="label_description" style="margin-top:5px; font-style:italic;">
                        Select a label to view details (if any).
                    </p>

                    <img id="label_image" style="display:none; max-width:150px; margin-top:5px;">
                    <p id="image_placeholder" style="color:#999; font-style:italic; display:none;"></p>

                    <br>

                    <label for='label_value'>Select a value:</label>
                    <select id="label_value" name="label_value" class="dropdown" required onchange="checkCustomValue()">
                        <option value="custom">Enter Custom Value</option>
                    </select>

                    <input type="text" id="custom_label_value" name="custom_label_value"
                           placeholder="Enter custom value" style="display:none;"><br><br>

                    <!-- Confidence slider if needed -->
                    <label for="confidence_slider">Confidence (0.0 - 1.0):</label>
                    <input type="range" id="confidence_slider" name="confidence_slider"
                           min="0" max="1" step="0.01" value="1.0"
                           oninput="sliderValueDisplay.value = confidence_slider.value">
                    <output id="sliderValueDisplay">1.0</output><br><br>

                    <button type='submit' class="add-label-button">Add Label</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

    return html_template


@app.route('/fetch_subfolder_contents/<string:type_name>/<path:label_type>/<string:subfolder>')
def fetch_subfolder_contents(type_name, label_type, subfolder):
    """
    Fetches the contents (JSON description and image) of a subfolder.
    """
    subfolder_path = f"./types/{type_name}/labels/{label_type}/{subfolder}"
    description = None
    image = None

    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        for file in os.listdir(subfolder_path):
            if file.endswith(".json"):
                json_data = load_json_as_dict(os.path.join(subfolder_path, file))
                description = json_data.get("description", "No description available.")
            elif file.endswith((".jpg", ".png", ".jpeg")):
                image = f"{type_name}/labels/{label_type}/{subfolder}/{file}"  # Updated path

    return jsonify({"description": description, "image": image})


@app.route('/get_subfolder_contents/<string:type_name>/<path:label_type>/<string:subfolder>')
def get_subfolder_contents(type_name, label_type, subfolder):
    """
    Fetches the contents (JSON description and image) of a subfolder.
    """
    subfolder_path = f"./types/{type_name}/labels/{label_type}/{subfolder}"
    description = None
    image = None

    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        for file in os.listdir(subfolder_path):
            if file.endswith(".json"):
                json_data = load_json_as_dict(os.path.join(subfolder_path, file))
                description = json_data.get("description", "No description available.")
            elif file.endswith((".jpg", ".png", ".jpeg")):
                image = f"{type_name}/labels/{label_type}/{subfolder}/{file}"  # Corrected image path

    return jsonify({"description": description, "image": image})


@app.route('/get_label_options/<string:type_name>/<path:label_type>')
def get_label_options(type_name, label_type):
    """
    Fetches options from a subfolder within the labels directory based on selection.
    """
    labels_path = f"./types/{type_name}/labels/{label_type}"
    options = []

    if os.path.exists(labels_path) and os.path.isdir(labels_path):
        for file in os.listdir(labels_path):
            if file.endswith(".json"):
                name = os.path.splitext(file)[0]
                options.append(name.capitalize())

    return jsonify({"options": options})



@app.route('/biography_addlabel_submit/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['POST'])
def biography_addlabel_submit(type_name, biography_name, entry_index):
    """
    Handles the submission of a new label, including custom string values and confidence.
    Ensures proper validation and prevents duplicate entries.
    """
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    bio_data = load_json_as_dict(json_file_path)

    # Ensure entry exists
    if entry_index >= len(bio_data["entries"]):
        flash("Error: Entry not found.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    entry = bio_data["entries"][entry_index]

    # Ensure labels list exists
    if "labels" not in entry:
        entry["labels"] = []

    # Get label details from form
    label_name = request.form.get("label_type", "").strip()
    label_value = request.form.get("label_value", "").strip()
    custom_value = request.form.get("custom_label_value", "").strip()

    # Fetch the confidence from the slider (default to 1.0 if missing/invalid)
    confidence_str = request.form.get("confidence_slider", "1.0").strip()
    try:
        confidence_val = float(confidence_str)
    except ValueError:
        confidence_val = 1.0

    # Prevent empty label names
    if not label_name:
        flash("Error: Label name cannot be empty.", "error")
        return redirect(f"/biography_addlabel/{type_name}/{biography_name}/{entry_index}")

    # Determine if label allows free-text input (e.g., first_name.json)
    label_json_path = f"./types/{type_name}/labels/{label_name}.json"
    label_type = ""

    if os.path.exists(label_json_path):
        label_data = load_json_as_dict(label_json_path)
        label_type = label_data.get("type", "").lower()  # Ensure lowercase comparison

    # If label type is "string" or user selected "custom", enforce using custom input
    if label_type == "string" or label_value == "custom":
        if not custom_value:
            flash("Error: Custom label value cannot be empty.", "error")
            return redirect(f"/biography_addlabel/{type_name}/{biography_name}/{entry_index}")
        label_value = custom_value  # Save the manually entered value

    # Build the new label object (including confidence)
    new_label = {
        "label": label_name,
        "value": label_value,
        "confidence": confidence_val
    }

    # Prevent duplicate label entries (optional uniqueness check)
    if new_label not in entry["labels"]:
        entry["labels"].append(new_label)
        save_dict_as_json(json_file_path, bio_data)
        flash(f"Label '{label_name}' with value '{label_value}' added successfully!", "success")
    else:
        flash(f"The label '{label_name}' with value '{label_value}' already exists.", "warning")

    return redirect(f"/biography/{type_name}/{biography_name}")


@app.route('/archived_biographies/<string:type_name>')
def archived_biographies(type_name):
    archive_path = f"./types/{type_name}/archived_biographies"
    
    # Ensure the archive folder exists, but only if necessary
    if not os.path.exists(archive_path) or not any(file.endswith(".json") for file in os.listdir(archive_path)):
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Archived Biographies - {type_name.capitalize()}</title>
            <link rel="stylesheet" href="/static/styles.css">
        </head>
        <body>
            <div class="container">
                <a href="/type/{type_name}" class="button">Back</a>
                <h1>Archived Biographies</h1>
                <p>No archived biographies found.</p>
            </div>
        </body>
        </html>
        """

    archived_list = ""
    for file in os.listdir(archive_path):
        if file.endswith(".json"):
            file_path = os.path.join(archive_path, file)
            bio_data = load_json_as_dict(file_path)

            # Extract original name and archived timestamp
            name = bio_data.get("name", file[:-5]).capitalize()  # Default to filename if name missing
            archived_date = bio_data.get("archived_on", "Unknown Time")

            archived_list += f"""
                <div class="archived-item">
                    <p><strong>{name}</strong></p>
                    <p class="timestamp">Archived: {archived_date}</p>
                    <button class="restore-button" onclick="restoreBiography('{type_name}', '{file[:-5]}')">Restore</button>
                </div>
            """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Archived Biographies - {type_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            function restoreBiography(typeName, biographyName) {{
                if (confirm("Are you sure you want to restore this biography?")) {{
                    fetch(`/biography_restore/${{typeName}}/${{biographyName}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Biography restored successfully.");
                                location.reload();
                            }} else {{
                                alert("Failed to restore biography.");
                            }}
                        }});
                }}
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href="/type/{type_name}" class="button">Back</a>
            <h1>Archived Biographies</h1>
            <div class="archived-container">
                {archived_list if archived_list else "<p>No archived biographies found.</p>"}
            </div>
        </div>
    </body>
    </html>
    """


@app.route('/biography_restore/<string:type_name>/<string:biography_name>', methods=['POST'])
def biography_restore(type_name, biography_name):
    archive_path = f"./types/{type_name}/archived_biographies"
    biographies_path = f"./types/{type_name}/biographies"

    # Ensure active biography directory exists
    os.makedirs(biographies_path, exist_ok=True)

    # Paths to move
    archived_json = os.path.join(archive_path, f"{biography_name}.json")
    biography_json = os.path.join(biographies_path, f"{biography_name}.json")
    archived_folder = os.path.join(archive_path, biography_name)
    biography_folder = os.path.join(biographies_path, biography_name)

    # Check if archive exists before proceeding
    if not os.path.exists(archived_json):
        return jsonify({"error": "Archived biography not found"}), 404

    try:
        # Restore JSON file (remove "archived_on" key)
        restored_data = load_json_as_dict(archived_json)
        restored_data.pop("archived_on", None)  # Remove archive timestamp

        # Save updated JSON in biographies folder
        save_dict_as_json(biography_json, restored_data)

        # Remove from archive
        os.remove(archived_json)

        # Restore subfolder if it exists
        if os.path.exists(archived_folder):
            shutil.move(archived_folder, biography_folder)

        return jsonify({"message": "Biography restored successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to restore biography: {str(e)}"}), 500

@app.route('/archived_biography/<string:type_name>/<string:biography_name>')
def archived_biography_page(type_name, biography_name):
    archive_path = f"./types/{type_name}/archived_biographies/{biography_name}.json"

    if not os.path.exists(archive_path):
        return f"""
        <h1>Error: Archived Biography Not Found</h1>
        <p>The file <code>{archive_path}</code> does not exist.</p>
        <a href='/archived_biographies/{type_name}' class='back-link'>Back</a>
        """, 404

    # Load biography data
    asDict = load_json_as_dict(archive_path)

    # Extract correct name and timestamp
    display_name = asDict.get("name", biography_name)  # Show actual name if present
    readable_time = asDict.get("archived_on", "Unknown Time")  # Show when archived
    description = asDict.get("description", "No description available.")

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{display_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            function restoreBiography(typeName, biographyName) {{
                if (confirm("Are you sure you want to restore this biography?")) {{
                    fetch(`/biography_restore/${{typeName}}/${{biographyName}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Biography restored successfully.");
                                window.location.href = "/type/" + typeName;
                            }}
                        }});
                }}
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href="/archived_biographies/{type_name}" class="button">Back</a>
            <h1>{display_name.capitalize()}</h1>
            <p class="timestamp">Archived: {readable_time}</p>
            <p class="description">{description}</p>

            <!-- Restore Biography Button -->
            <button class="restore-button" onclick="restoreBiography('{type_name}', '{biography_name}')">Restore Biography</button>
        </div>
    </body>
    </html>
    """


@app.route('/biography_edit/<string:type_name>/<string:biography_name>', methods=['GET', 'POST'])
def biography_edit(type_name, biography_name):
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    biography_folder_path = f"./types/{type_name}/biographies/{biography_name}"

    if not os.path.exists(biography_path):
        return f"""
        <h1>Error: Biography Not Found</h1>
        <p>The file <code>{biography_path}</code> does not exist.</p>
        <a href='/type/{type_name}' class='back-link'>Back</a>
        """, 404

    # Load biography data
    bio_data = load_json_as_dict(biography_path)

    # Ensure timestamp exists; if missing, create one
    if "timestamp" not in bio_data:
        new_timestamp = str(int(time.time()))  # Generate a new timestamp
        bio_data["timestamp"] = new_timestamp
        bio_data["readable_time"] = datetime.fromtimestamp(int(new_timestamp)).strftime('%Y-%m-%d %H:%M:%S')

        # Save the updated JSON with the timestamp
        save_dict_as_json(biography_path, bio_data)

    if request.method == 'POST':
        new_name = request.form['biography_name'].strip().replace(" ", "_")
        new_description = request.form['description']

        # Use the existing timestamp
        timestamp = bio_data["timestamp"]
        new_biography_name = f"{new_name}_{timestamp}"  # Keep same timestamp
        new_biography_path = f"./types/{type_name}/biographies/{new_biography_name}.json"
        new_folder_path = f"./types/{type_name}/biographies/{new_biography_name}"

        # Update the JSON data
        bio_data["name"] = new_name
        bio_data["description"] = new_description

        # Rename JSON file and folder if the name has changed
        if new_biography_name != biography_name:
            os.rename(biography_path, new_biography_path)  # Rename JSON file
            if os.path.exists(biography_folder_path):
                os.rename(biography_folder_path, new_folder_path)  # Rename folder

        # Save updated JSON
        save_dict_as_json(new_biography_path, bio_data)

        flash(f"Biography '{new_name}' updated successfully!", "success")
        return redirect(f"/biography/{type_name}/{new_biography_name}")  # Redirect to new page

    # Get current values
    display_name = bio_data.get("name", "Unknown Name")
    description = bio_data.get("description", "No description available.")

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Edit Biography</title>
        <link rel="stylesheet" href="/static/styles.css">
    </head>
    <body>
        <div class="edit-biography-container">
            <a href='/biography/{type_name}/{biography_name}' class="back-link">Back</a>
            <h1>Edit Biography</h1>

            <form method="post">
                <label for="biography_name">Biography Name:</label>
                <input type="text" name="biography_name" value="{display_name}" required>

                <label for="description">Description:</label>
                <textarea name="description" required>{description}</textarea>

                <button type="submit">Save Changes</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.route('/biography_editlabel/<string:type_name>/<string:biography_name>/<int:entry_index>/<int:label_index>', methods=['GET','POST'])
def biography_editlabel(type_name, biography_name, entry_index, label_index):
    """
    Displays the Edit Label page, letting us pick from subfolder-based label folders,
    show images, and preserve confidence & custom typed values.
    """

    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(biography_path)
    entries = bio_data.get("entries", [])
    if entry_index >= len(entries):
        return f"<h1>Error: Entry Not Found</h1>", 404

    labels_list = entries[entry_index].get("labels", [])
    if label_index >= len(labels_list):
        return f"<h1>Error: Label Not Found</h1>", 404

    label_data = labels_list[label_index]
    label_name   = label_data.get("label","")
    label_value  = label_data.get("value","")
    confidence   = label_data.get("confidence", 1.0)

    display_name = bio_data.get("name", biography_name)

    # ----------------- POST: Save Changes -----------------
    if request.method == 'POST':
        updated_label_name = request.form.get("label_name", "").strip()
        updated_label_value = request.form.get("label_value", "").strip()
        if updated_label_value == "custom":
            updated_label_value = request.form.get("custom_label_value","").strip()
        
        conf_str = request.form.get("confidence_slider","1.0")
        try:
            updated_conf = float(conf_str)
        except ValueError:
            updated_conf = 1.0

        # Update the JSON
        labels_list[label_index] = {
            "label": updated_label_name,
            "value": updated_label_value,
            "confidence": updated_conf
        }
        save_dict_as_json(biography_path, bio_data)
        flash("Label updated successfully!", "success")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # ----------------- GET: Show Form -----------------
    labels_path = f"./types/{type_name}/labels"
    label_folders = [f for f in os.listdir(labels_path) if f.endswith(".json")]

    def prettify_label_name(raw: str) -> str:
        return " ".join(w.capitalize() for w in raw.split("_"))

    # Build a data structure: { "folder_name": { "pretty_name":..., "values": [...], "images": {...} } }
    label_info_dict = {}
    for label_file in label_folders:
        folder_name = os.path.splitext(label_file)[0]
        label_folder_path = os.path.join(labels_path, folder_name)
        label_json_path   = os.path.join(labels_path, label_file)
        data_json = load_json_as_dict(label_json_path)

        base_values = data_json.get("values", [])
        images_map  = {}

        if os.path.exists(label_folder_path) and os.path.isdir(label_folder_path):
            subfolder_files = [sf for sf in os.listdir(label_folder_path) if sf.endswith(".json")]
            sub_vals = [os.path.splitext(sf)[0] for sf in subfolder_files]
            combined = list(set(base_values + sub_vals))

            # Gather matching images
            image_files = [im for im in os.listdir(label_folder_path) if im.endswith((".jpg",".png"))]
            for val in combined:
                matched_img = next((im for im in image_files if os.path.splitext(im)[0] == val), None)
                if matched_img:
                    images_map[val] = f"/serve_label_image/{type_name}/{folder_name}/{matched_img}"
                else:
                    images_map[val] = None
        else:
            combined = base_values

        label_info_dict[folder_name] = {
            "pretty_name": prettify_label_name(folder_name),
            "values": combined,
            "images": images_map
        }

    # Convert to JSON for front-end
    import json
    label_info_json = json.dumps(label_info_dict)

    # 1) The top portion of our HTML
    html_top = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Edit Label</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            let labelInfo = {label_info_json};

            function updateLabelValues() {{
                let selectedFolder = document.getElementById("label_name").value;
                let valSelect      = document.getElementById("label_value");
                let customInput    = document.getElementById("custom_label_value");
                let imgContainer   = document.getElementById("label_image");
                let placeholder    = document.getElementById("image_placeholder");

                // Reset
                valSelect.innerHTML = "";
                customInput.style.display = "none";
                customInput.value = "";

                if (labelInfo[selectedFolder]) {{
                    let vals = labelInfo[selectedFolder].values;
                    vals.forEach(v => {{
                        let opt = document.createElement("option");
                        opt.value = v;
                        opt.textContent = v;
                        valSelect.appendChild(opt);
                    }});

                    // always add 'custom'
                    let customOpt = document.createElement("option");
                    customOpt.value = "custom";
                    customOpt.textContent = "Enter Custom Value";
                    valSelect.appendChild(customOpt);
                }} else {{
                    // no known folder => only 'custom'
                    let onlyCust = document.createElement("option");
                    onlyCust.value = "custom";
                    onlyCust.textContent = "Enter Custom Value";
                    valSelect.appendChild(onlyCust);
                }}

                // Hide or reset the image placeholder
                imgContainer.style.display = "none";
                placeholder.style.display  = "none";
            }}

            function checkCustomValue() {{
                let folderSel   = document.getElementById("label_name").value;
                let valSelect   = document.getElementById("label_value");
                let customInput = document.getElementById("custom_label_value");

                let imgContainer = document.getElementById("label_image");
                let placeholder  = document.getElementById("image_placeholder");

                if (valSelect.value === "custom") {{
                    valSelect.style.display = "none";
                    customInput.style.display = "block";
                    customInput.required = true;

                    imgContainer.style.display = "none";
                    placeholder.style.display  = "block";
                    placeholder.innerHTML = "No image for custom value";
                }} else {{
                    customInput.style.display = "none";
                    customInput.required = false;
                    valSelect.style.display = "inline-block";

                    let chosenVal = valSelect.value;
                    let imagesMap = labelInfo[folderSel].images;
                    if (imagesMap[chosenVal]) {{
                        imgContainer.src = imagesMap[chosenVal];
                        imgContainer.style.display = "block";
                        placeholder.style.display  = "none";
                    }} else {{
                        placeholder.style.display = "block";
                        placeholder.innerHTML = "Expected Image: " + chosenVal + ".jpg or .png";
                        imgContainer.style.display = "none";
                    }}
                }}
            }}

            window.onload = function() {{
                updateLabelValues();

                let existingVal = "{label_value}";
                let valSelect   = document.getElementById("label_value");

                let found = false;
                for (let i = 0; i < valSelect.options.length; i++) {{
                    if (valSelect.options[i].value === existingVal) {{
                        valSelect.selectedIndex = i;
                        found = true;
                        break;
                    }}
                }}

                if (!found) {{
                    for (let i = 0; i < valSelect.options.length; i++) {{
                        if (valSelect.options[i].value === "custom") {{
                            valSelect.selectedIndex = i;
                            break;
                        }}
                    }}
                    document.getElementById("custom_label_value").value = existingVal;
                }}

                checkCustomValue();
            }};
        </script>
    </head>
    <body>
        <div class="edit-label-container">
            <a href='/biography/{type_name}/{biography_name}' class="back-link">Back</a>
            <h1>Edit Label for {display_name}</h1>

            <form method="post">
                <!-- Label Folder -->
                <label for="label_name">Label Folder:</label>
                <select name="label_name" id="label_name"
                        onchange="updateLabelValues(); checkCustomValue();" required>
    """

    # 2) We build the <option> list in Python
    html_options = ""
    for folder, info in label_info_dict.items():
        selected = "selected" if folder == label_name else ""
        html_options += f'<option value="{folder}" {selected}>{info["pretty_name"]}</option>'

    # 3) The bottom portion of the HTML
    html_bottom = f"""
                </select>

                <!-- Image or placeholder -->
                <p id="image_placeholder" style="color: #888; font-style: italic; display: none;"></p>
                <img id="label_image" style="display: none; max-width: 150px; margin-top: 5px;"><br><br>

                <!-- Label Value -->
                <label for="label_value">Label Value:</label>
                <select name="label_value" id="label_value" onchange="checkCustomValue()" required>
                    <!-- Populated dynamically -->
                </select>
                <input type="text" id="custom_label_value" name="custom_label_value"
                       placeholder="Enter custom value" style="display:none;"><br><br>

                <!-- Confidence Slider -->
                <label for="confidence_slider">Confidence (0.0 - 1.0):</label>
                <input type="range" id="confidence_slider" name="confidence_slider"
                       min="0" max="1" step="0.01" value="{confidence}"
                       oninput="sliderValueDisplay.value = confidence_slider.value">
                <output id="sliderValueDisplay">{confidence}</output><br><br>

                <button type="submit">Save Changes</button>
            </form>
        </div>
    </body>
    </html>
    """

    # Finally, combine all parts into one string
    final_html = html_top + html_options + html_bottom
    return final_html




@app.route('/biography_editlabel_submit/<string:type_name>/<string:biography_name>/<int:entry_index>/<int:label_index>', methods=['POST'])
def biography_editlabel_submit(type_name, biography_name, entry_index, label_index):
    """
    POST route for saving changes to an existing label (name, value, confidence).
    This is separate from the GET-based `biography_editlabel` route.
    """

    # 1. Load the biography JSON
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return "<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(biography_path)
    entries = bio_data.get("entries", [])

    # Ensure the entry index is valid
    if entry_index >= len(entries):
        flash("Error: Entry index out of range.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # Labels in that entry
    labels_list = entries[entry_index].get("labels", [])
    if label_index >= len(labels_list):
        flash("Error: Label index out of range.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # 2. Parse form fields
    updated_label_name = request.form.get("label_name", "").strip()
    updated_label_value = request.form.get("label_value", "").strip()

    # If the user chose "custom", use the typed text
    if updated_label_value == "custom":
        custom_input = request.form.get("custom_label_value", "").strip()
        if custom_input:
            updated_label_value = custom_input
        else:
            flash("Error: Custom label value cannot be empty.", "error")
            return redirect(f"/biography/{type_name}/{biography_name}")

    # Parse confidence slider
    confidence_str = request.form.get("confidence_slider", "1.0").strip()
    try:
        updated_confidence = float(confidence_str)
    except ValueError:
        updated_confidence = 1.0

    # 3. Update the JSON
    labels_list[label_index] = {
        "label": updated_label_name,   # raw folder name or label name
        "value": updated_label_value,  # chosen or typed value
        "confidence": updated_confidence
    }

    # 4. Save
    save_dict_as_json(biography_path, bio_data)

    flash("Label updated successfully!", "success")
    return redirect(f"/biography/{type_name}/{biography_name}")



@app.route('/events_add', methods=['GET','POST'])
def events_add():
    """
    Lets a user create a new event referencing multiple types (people, organisations, etc.),
    with an optional date approach (exact/partial) or subfolder approach (like 'person_decade').
    """

    # 1) PATH to the events directory
    events_biographies_path = "./types/events/biographies"

    # Ensure the folder exists
    os.makedirs(events_biographies_path, exist_ok=True)

    # 2) If POST => process form submission
    if request.method == 'POST':
        # a) Basic fields
        relationship = request.form.get("relationship","").strip()  # e.g. "EMPLOYED_BY"
        person_id    = request.form.get("person_id","").strip()
        org_id       = request.form.get("org_id","").strip()
        notes        = request.form.get("notes","").strip()

        # b) Approach => date or subfolder
        chosen_approach = request.form.get("approach","date")
        # if date => partial vs exact
        date_mode = request.form.get("date_mode","exact")
        start_value = ""
        end_value   = ""

        if chosen_approach == "date":
            # user picking partial vs exact
            if date_mode == "exact":
                start_value = request.form.get("start_full_date","").strip()  # e.g. "1939-09-01"
                end_value   = request.form.get("end_full_date","").strip()
            else:
                start_value = request.form.get("start_partial_year","").strip()  # e.g. "1939"
                end_value   = request.form.get("end_partial_year","").strip()
        else:
            # subfolder approach => e.g. 'person_decade'
            # user picks from subfolder for start, end
            start_sub_val = request.form.get("start_sub_val","").strip()
            if start_sub_val == "custom":
                start_sub_val = request.form.get("start_custom_val","").strip() or "Custom"
            end_sub_val = request.form.get("end_sub_val","").strip()
            if end_sub_val == "custom":
                end_sub_val = request.form.get("end_custom_val","").strip() or "Custom"

            start_value = start_sub_val
            end_value   = end_sub_val

        # c) Build new event JSON structure
        import time
        timestamp = str(int(time.time()))  # unique-ish
        new_event_id = f"E_{timestamp}"
        new_event_data = {
            "id": new_event_id,
            "relationship": relationship,
            "person_id": person_id,
            "org_id": org_id,
            "approach": chosen_approach,  # "date" or "person_decade" or something
            "date_mode": date_mode,       # "exact" or "partial" if date
            "start_value": start_value,
            "end_value": end_value,
            "notes": notes
        }

        # d) Save new event to e.g. /types/events/biographies/E_<timestamp>.json
        new_event_path = os.path.join(events_biographies_path, f"{new_event_id}.json")
        save_dict_as_json(new_event_path, new_event_data)

        flash(f"Event {new_event_id} created successfully!", "success")
        return redirect("/events_list")  # or wherever you want to go

    # 3) If GET => show form
    # We'll gather known people and org IDs from your existing directories to populate dropdowns

    # known people
    people_path = "./types/people/biographies"
    people_files = [f for f in os.listdir(people_path) if f.endswith(".json")]
    people_options = []
    for pf in people_files:
        # load each JSON, extract ID or name
        p_data = load_json_as_dict(os.path.join(people_path, pf))
        pid    = p_data.get("id", pf[:-5])  # fallback
        pname  = p_data.get("name", pid)
        people_options.append((pid, pname))

    # known organisations
    org_path = "./types/organisations/biographies"
    org_files = [f for f in os.listdir(org_path) if f.endswith(".json")]
    org_options = []
    for of in org_files:
        o_data = load_json_as_dict(os.path.join(org_path, of))
        oid    = o_data.get("id", of[:-5])
        oname  = o_data.get("name", oid)
        org_options.append((oid, oname))

    # We'll also define relationships
    possible_relationships = ["EMPLOYED_BY","LIVED_IN","FOUNDED","COLLABORATED","VISITED"]

    # We'll define a plain triple-quoted string for the form
    html_form = r"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Add Event</title>
      <style>
        .hidden { display: none; }
      </style>
      <script>
      function onApproachChange() {
        let apSel = document.getElementById("approach").value;
        let dateSec = document.getElementById("date_approach_section");
        let subSec  = document.getElementById("subfolder_approach_section");
        if(apSel==="date") {
          dateSec.style.display="block";
          subSec.style.display="none";
        } else {
          dateSec.style.display="none";
          subSec.style.display="block";
        }
      }
      function onDateModeChange(prefix) {
        let exactRad = document.getElementById(prefix+"_date_mode_exact");
        let partialRad= document.getElementById(prefix+"_date_mode_partial");
        let exactDiv = document.getElementById(prefix+"_exactDiv");
        let partDiv  = document.getElementById(prefix+"_partialDiv");
        if(exactRad.checked) {
          exactDiv.style.display="block";
          partDiv.style.display="none";
        } else {
          exactDiv.style.display="none";
          partDiv.style.display="block";
        }
      }
      function checkCustom(prefix) {
        let sel= document.getElementById(prefix+"_sub_val");
        let cust= document.getElementById(prefix+"_custom_val");
        if(sel.value==="custom"){
          sel.style.display="none";
          cust.style.display="inline-block";
        } else {
          cust.style.display="none";
          sel.style.display="inline-block";
        }
      }
      window.onload=function(){
        onApproachChange();
        onDateModeChange("start");
        onDateModeChange("end");
      }
      </script>
    </head>
    <body>
      <h1>Add Event</h1>
      <form method="post">
        <label>Relationship:</label>
        <select name="relationship" id="relationship">
          RELATIONSHIP_OPTIONS
        </select>
        <br><br>

        <label>Person:</label>
        <select name="person_id" id="person_id">
          PEOPLE_OPTIONS
        </select>
        <br>

        <label>Organisation:</label>
        <select name="org_id" id="org_id">
          ORG_OPTIONS
        </select>
        <br>

        <label>Notes:</label>
        <input type="text" name="notes" size="50"><br><br>

        <h2>Approach:</h2>
        <select id="approach" name="approach" onchange="onApproachChange()">
          <option value="date">Date</option>
          <option value="person_decade">Person Decade</option>
        </select>

        <div id="date_approach_section" style="display:none;">
          <!-- Start date approach -->
          <h3>Start (Date)</h3>
          <label>
            <input type="radio" id="start_date_mode_exact" name="date_mode" value="exact"
                   onclick="onDateModeChange('start')" checked>Exact
          </label>
          <label>
            <input type="radio" id="start_date_mode_partial" name="date_mode" value="partial"
                   onclick="onDateModeChange('start')">Partial
          </label>
          <div id="start_exactDiv">
            <label>Exact Start Date:</label>
            <input type="date" name="start_full_date">
          </div>
          <div id="start_partialDiv" class="hidden">
            <label>Partial Start Year:</label>
            <input type="number" name="start_partial_year" min="1" max="9999">
          </div>

          <!-- End date approach -->
          <h3>End (Date)</h3>
          <label>
            <input type="radio" id="end_date_mode_exact" name="end_date_mode" value="exact"
                   onclick="onDateModeChange('end')" checked>Exact
          </label>
          <label>
            <input type="radio" id="end_date_mode_partial" name="end_date_mode" value="partial"
                   onclick="onDateModeChange('end')">Partial
          </label>
          <div id="end_exactDiv">
            <label>Exact End Date:</label>
            <input type="date" name="end_full_date">
          </div>
          <div id="end_partialDiv" class="hidden">
            <label>Partial End Year:</label>
            <input type="number" name="end_partial_year" min="1" max="9999">
          </div>
        </div>

        <div id="subfolder_approach_section" style="display:none;">
          <!-- e.g. person_decade approach -->
          <h3>Start (Subfolder)</h3>
          <select id="start_sub_val" name="start_sub_val" onchange="checkCustom('start')">
            <option value="1920s">1920s</option>
            <option value="1930s">1930s</option>
            <option value="custom">Enter Custom Value</option>
          </select>
          <input type="text" id="start_custom_val" name="start_custom_val" style="display:none;">

          <h3>End (Subfolder)</h3>
          <select id="end_sub_val" name="end_sub_val" onchange="checkCustom('end')">
            <option value="1920s">1920s</option>
            <option value="1930s">1930s</option>
            <option value="custom">Enter Custom Value</option>
          </select>
          <input type="text" id="end_custom_val" name="end_custom_val" style="display:none;">
        </div>

        <br><br>
        <button type="submit">Add Event</button>
      </form>
    </body>
    </html>
    """

    # 4) We'll dynamically build the <option> lists for relationships, people, orgs

    # relationship
    possible_relationships = ["EMPLOYED_BY","LIVED_IN","VISITED","FOUNDED","COLLABORATED"]
    relationship_html = "".join(f'<option value="{r}">{r}</option>' for r in possible_relationships)

    # People
    people_dir = "./types/people/biographies"
    people_opts = []
    if os.path.exists(people_dir):
        for pf in os.listdir(people_dir):
            if pf.endswith(".json"):
                p_data = load_json_as_dict(os.path.join(people_dir, pf))
                pid    = p_data.get("id", pf[:-5])
                pname  = p_data.get("name", pid)
                people_opts.append(f'<option value="{pid}">{pname}</option>')
    people_html = "".join(people_opts)

    # Orgs
    orgs_dir = "./types/organisations/biographies"
    org_opts = []
    if os.path.exists(orgs_dir):
        for of in os.listdir(orgs_dir):
            if of.endswith(".json"):
                o_data = load_json_as_dict(os.path.join(orgs_dir, of))
                oid    = o_data.get("id", of[:-5])
                oname  = o_data.get("name", oid)
                org_opts.append(f'<option value="{oid}">{oname}</option>')
    orgs_html = "".join(org_opts)

    # 5) Insert them into the HTML with .replace
    final_form = html_form
    final_form = final_form.replace("RELATIONSHIP_OPTIONS", relationship_html)
    final_form = final_form.replace("PEOPLE_OPTIONS", people_html)
    final_form = final_form.replace("ORG_OPTIONS", orgs_html)

    return final_form


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

