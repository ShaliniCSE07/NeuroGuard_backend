from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
from werkzeug.utils import secure_filename

from database import init_db
from models import insert_game_result, get_user_results, get_baseline
from baseline import establish_baseline, auto_build_all_baselines
from change_radar import analyze_change, full_radar
from integration import ingest_result, get_recommendations

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

# Photo upload folder
UPLOAD_DIR = os.path.join(FRONTEND_DIR, "games", "public", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])


# ---------- Static frontend ----------
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------- API ----------
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/results", methods=["POST"])
def post_result():
    data = request.get_json(force=True)
    ok, msg, baseline = ingest_result(data)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"status": "stored", "baseline_ready": baseline is not None,
                    "baseline": baseline}), 201


@app.route("/api/results/<user_id>", methods=["GET"])
def get_results_route(user_id):
    game_type = request.args.get("game_type")
    return jsonify(get_user_results(user_id, game_type))


@app.route("/api/baseline/<user_id>", methods=["GET"])
def baseline_for_user(user_id):
    return jsonify(auto_build_all_baselines(user_id))


@app.route("/api/baseline/<user_id>/<game_type>", methods=["GET"])
def baseline_for_game(user_id, game_type):
    b = establish_baseline(user_id, game_type)
    if not b:
        return jsonify({"status": "insufficient_data"}), 200
    return jsonify(b)


@app.route("/api/radar/<user_id>", methods=["GET"])
def radar(user_id):
    return jsonify(full_radar(user_id))


@app.route("/api/radar/<user_id>/<game_type>", methods=["GET"])
def radar_single(user_id, game_type):
    return jsonify(analyze_change(user_id, game_type))


@app.route("/api/dashboard/<user_id>", methods=["GET"])
def dashboard(user_id):
    radar_data = full_radar(user_id)
    recs = get_recommendations(user_id, radar_data)
    results = get_user_results(user_id)
    return jsonify({
        "user_id": user_id,
        "total_sessions": len(results),
        "results": results,
        "radar": radar_data,
        "recommendations": recs,
    })


@app.route("/api/recommendations/<user_id>", methods=["GET"])
def recommendations(user_id):
    return jsonify(get_recommendations(user_id, full_radar(user_id)))


# ---------- MEMBER 3 INTEGRATION: PHOTO UPLOAD & ACTIVITIES ----------

@app.route("/api/memories", methods=["GET"])
def list_memories():
    user_id = request.args.get("user_id", "U001")
    if not os.path.exists(UPLOAD_DIR):
        return jsonify([])
    
    files = [f for f in os.listdir(UPLOAD_DIR) if f.startswith(user_id + "_")]
    memories = []
    for f in files:
        title = f.replace(f"{user_id}_", "").split(".")[0]
        memories.append({
            "id": f,
            "title": title,
            "image_url": f"/games/public/uploads/{f}"
        })
    return jsonify(memories)


@app.route("/api/memories", methods=["POST"])
def add_memory():
    user_id = request.form.get("user_id", "U001")
    file = request.files.get("image") or request.files.get("photo") or request.files.get("file")
    title = request.form.get("title", "My Memory")
    
    if not file:
        return jsonify({"error": "no image uploaded"}), 400
        
    safe_name = secure_filename(file.filename)
    filename = f"{user_id}_{title}_{safe_name}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)
    
    return jsonify({"status": "ok", "message": "Memory saved", "id": filename}), 201


@app.route("/api/activities/<user_id>/session", methods=["GET"])
def start_member3_activity(user_id):
    if not os.path.exists(UPLOAD_DIR):
        return jsonify({"error": "No memories found"}), 404
        
    files = [f for f in os.listdir(UPLOAD_DIR) if f.startswith(user_id + "_")]
    if not files:
        return jsonify({"error": "No memories found"}), 404
        
    latest_file = files[-1]
    image_url = f"/games/public/uploads/{latest_file}" 

    return jsonify({
        "session_id": f"session-{uuid.uuid4().hex[:6]}",
        "difficulty_level": 1,
        "questions": [
            {
                "question_id": "q1",
                "memory_id": latest_file,
                "kind": "mcq",
                "prompt": "Who is in this photo?",
                "photo_url": image_url,
                "options": ["Mom", "Dad", "Sister"],
                "hints": ["Look at the hair.", "It starts with M."]
            },
            {
                "question_id": "q2",
                "memory_id": latest_file,
                "kind": "typed",
                "prompt": "What is the name of the person?",
                "photo_url": image_url,
                "options": [],
                "hints": ["It starts with M."]
            }
        ]
    })


@app.route("/api/activities/answer", methods=["POST"])
def answer_member3_activity():
    return jsonify({
        "correct": True,
        "message": "That's right!",
        "story": "This was a lovely day.",
        "reveal": False
    })


@app.route("/api/activities/complete", methods=["POST"])
def complete_activity():
    return jsonify({
        "message": "Great job looking at the photos!",
        "first_try_correct": 2,
        "questions_answered": 2,
        "memories_shared": 0,
        "hints_used": 0,
        "result": {"time_taken": 45}
    })


@app.route("/api/activities/stop", methods=["POST"])
def stop_member3_activity():
    return jsonify({"status": "stopped"})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)