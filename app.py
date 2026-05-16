from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
from collections import Counter
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB = "aviator.db"

# ─── Database Setup ───────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            multiplier REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_key TEXT NOT NULL,
            next_category TEXT NOT NULL,
            hit_count INTEGER DEFAULT 1,
            total_count INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Helper: multiplier → category ───────────────────────────
def categorize(m):
    if m < 2.0:
        return "LOW"       # 1x - 1.99x
    elif m < 5.0:
        return "MID"       # 2x - 4.99x
    elif m < 10.0:
        return "HIGH"      # 5x - 9.99x
    else:
        return "MEGA"      # 10x+

def category_label(cat):
    return {
        "LOW":  "2x এর নিচে (Low)",
        "MID":  "2x - 5x (Medium)",
        "HIGH": "5x - 10x (High)",
        "MEGA": "10x+ (Mega)"
    }.get(cat, cat)

# ─── Pattern Engine ───────────────────────────────────────────
class PatternEngine:

    def get_all_multipliers(self):
        conn = get_db()
        rows = conn.execute("SELECT multiplier FROM rounds ORDER BY id ASC").fetchall()
        conn.close()
        return [r["multiplier"] for r in rows]

    def get_categories(self, multipliers):
        return [categorize(m) for m in multipliers]

    # Markov Chain: আগের N রাউন্ড দেখে পরেরটা অনুমান
    def markov_analysis(self, categories, window=3):
        transitions = {}
        for i in range(len(categories) - window):
            key = tuple(categories[i:i+window])
            next_cat = categories[i+window]
            if key not in transitions:
                transitions[key] = Counter()
            transitions[key][next_cat] += 1

        # শেষ N রাউন্ডের pattern দেখো
        if len(categories) >= window:
            current_key = tuple(categories[-window:])
            if current_key in transitions:
                total = sum(transitions[current_key].values())
                probs = {k: round(v/total*100, 1) for k, v in transitions[current_key].items()}
                best = max(probs, key=probs.get)
                return {
                    "method": "Markov Chain",
                    "window": window,
                    "current_sequence": list(current_key),
                    "prediction": best,
                    "probabilities": probs,
                    "confidence": probs[best],
                    "seen_before": total,
                    "description": f"এই ধরনের সিকোয়েন্সে আগে {best} এসেছে {probs[best]}% সময়"
                }
        return None

    # Streak Analysis: পরপর একই ধরন কতবার
    def streak_analysis(self, categories):
        if not categories:
            return None
        current = categories[-1]
        streak = 1
        for c in reversed(categories[:-1]):
            if c == current:
                streak += 1
            else:
                break

        # ঐতিহাসিকভাবে এই streak এর পরে কি হয়েছে
        streak_outcomes = Counter()
        for i in range(len(categories) - 1):
            s = 1
            for j in range(i-1, -1, -1):
                if categories[j] == categories[i]:
                    s += 1
                else:
                    break
            if s == streak and i + 1 < len(categories):
                streak_outcomes[categories[i+1]] += 1

        result = {
            "method": "Streak Analysis",
            "current_streak": streak,
            "streak_type": current,
            "description": f"পরপর {streak}টা {category_label(current)} এসেছে"
        }

        if streak_outcomes:
            total = sum(streak_outcomes.values())
            probs = {k: round(v/total*100, 1) for k, v in streak_outcomes.items()}
            best = max(probs, key=probs.get)
            result["prediction"] = best
            result["probabilities"] = probs
            result["confidence"] = probs[best]
            result["after_streak_note"] = f"{streak}টা {current} এর পরে সাধারণত {category_label(best)} আসে ({probs[best]}%)"

        return result

    # Frequency: কোনটা কতবার আসে
    def frequency_analysis(self, categories, last_n=50):
        recent = categories[-last_n:] if len(categories) >= last_n else categories
        total = len(recent)
        if total == 0:
            return None
        counts = Counter(recent)
        probs = {k: round(counts.get(k, 0)/total*100, 1) for k in ["LOW","MID","HIGH","MEGA"]}
        return {
            "method": "Frequency Analysis",
            "last_n": last_n,
            "probabilities": probs,
            "description": f"শেষ {total} রাউন্ডে LOW={probs['LOW']}%, MID={probs['MID']}%, HIGH={probs['HIGH']}%, MEGA={probs['MEGA']}%"
        }

    # Cold Zone: কোনটা অনেকক্ষণ আসেনি
    def cold_zone_analysis(self, categories):
        alerts = []
        targets = {"HIGH": 10, "MEGA": 20, "MID": 5}
        for cat, threshold in targets.items():
            last_seen = None
            for i, c in enumerate(reversed(categories)):
                if c == cat:
                    last_seen = i
                    break
            if last_seen is None:
                last_seen = len(categories)
            if last_seen >= threshold:
                alerts.append({
                    "category": cat,
                    "label": category_label(cat),
                    "rounds_missing": last_seen,
                    "threshold": threshold,
                    "alert": f"⚠️ {category_label(cat)} শেষ {last_seen} রাউন্ড ধরে আসেনি!"
                })
        return alerts

    # Moving Average: Trend উপরে নাকি নিচে
    def moving_average(self, multipliers, short=5, long=15):
        if len(multipliers) < long:
            return None
        short_avg = sum(multipliers[-short:]) / short
        long_avg = sum(multipliers[-long:]) / long
        trend = "উর্ধ্বমুখী 📈" if short_avg > long_avg else "নিম্নমুখী 📉"
        return {
            "method": "Moving Average",
            "short_avg": round(short_avg, 2),
            "long_avg": round(long_avg, 2),
            "trend": trend,
            "description": f"শেষ {short} রাউন্ডের গড়: {round(short_avg,2)}x | শেষ {long} রাউন্ডের গড়: {round(long_avg,2)}x | Trend: {trend}"
        }

    # সব মিলিয়ে Final Suggestion
    def final_suggestion(self, analyses):
        votes = Counter()
        confidence_sum = {}

        for a in analyses:
            if a and "prediction" in a:
                pred = a["prediction"]
                conf = a.get("confidence", 50)
                votes[pred] += 1
                confidence_sum[pred] = confidence_sum.get(pred, 0) + conf

        if not votes:
            return {
                "prediction": "অনিশ্চিত",
                "confidence": 0,
                "message": "আরও ডেটা দরকার (কমপক্ষে ২০ রাউন্ড)"
            }

        best = max(votes, key=lambda x: (votes[x], confidence_sum.get(x, 0)))
        avg_conf = round(confidence_sum[best] / votes[best], 1)

        messages = {
            "LOW":  "⚠️ সতর্ক থাকো — 2x এর নিচে আসতে পারে",
            "MID":  "🟡 2x - 5x এর মধ্যে থামতে পারে",
            "HIGH": "🟢 5x - 10x পর্যন্ত যাওয়ার সম্ভাবনা আছে",
            "MEGA": "🔥 10x+ যাওয়ার সম্ভাবনা আছে!"
        }

        return {
            "prediction": best,
            "label": category_label(best),
            "confidence": avg_conf,
            "votes": dict(votes),
            "message": messages.get(best, ""),
            "note": "⚡ এটি শুধু Pattern Analysis — ১০০% নিশ্চিত না"
        }


engine = PatternEngine()

# ─── API Routes ───────────────────────────────────────────────

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "✅ Aviator Pattern Engine চালু আছে!", "version": "1.0"})

# নতুন রাউন্ড যোগ করো
@app.route("/add-round", methods=["POST"])
def add_round():
    data = request.get_json()
    multiplier = float(data.get("multiplier", 0))
    if multiplier <= 0:
        return jsonify({"error": "Multiplier 0 এর বেশি হতে হবে"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO rounds (multiplier, timestamp) VALUES (?, ?)",
        (multiplier, datetime.now().isoformat())
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) as c FROM rounds").fetchone()["c"]
    conn.close()

    return jsonify({
        "success": True,
        "multiplier": multiplier,
        "category": categorize(multiplier),
        "total_rounds": total,
        "message": f"✅ {multiplier}x যোগ হয়েছে। মোট {total} রাউন্ড।"
    })

# Pattern Analysis
@app.route("/analysis", methods=["GET"])
def analysis():
    multipliers = engine.get_all_multipliers()

    if len(multipliers) < 10:
        return jsonify({
            "status": "insufficient_data",
            "total_rounds": len(multipliers),
            "message": f"আরও {10 - len(multipliers)} টা রাউন্ড দরকার বিশ্লেষণের জন্য",
            "suggestion": None
        })

    categories = engine.get_categories(multipliers)

    markov3 = engine.markov_analysis(categories, window=3)
    markov5 = engine.markov_analysis(categories, window=5)
    streak   = engine.streak_analysis(categories)
    freq     = engine.frequency_analysis(categories)
    cold     = engine.cold_zone_analysis(categories)
    ma       = engine.moving_average(multipliers)

    analyses = [markov3, markov5, streak]
    suggestion = engine.final_suggestion(analyses)

    last_10 = multipliers[-10:]
    last_cats = categories[-10:]

    return jsonify({
        "status": "ok",
        "total_rounds": len(multipliers),
        "last_10_multipliers": last_10,
        "last_10_categories": last_cats,
        "analyses": {
            "markov_3": markov3,
            "markov_5": markov5,
            "streak": streak,
            "frequency": freq,
            "moving_average": ma
        },
        "cold_alerts": cold,
        "suggestion": suggestion
    })

# ইতিহাস দেখো
@app.route("/history", methods=["GET"])
def history():
    limit = request.args.get("limit", 100, type=int)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM rounds ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return jsonify({
        "rounds": [dict(r) for r in rows],
        "count": len(rows)
    })

# সব ডেটা মুছো (Reset)
@app.route("/reset", methods=["POST"])
def reset():
    conn = get_db()
    conn.execute("DELETE FROM rounds")
    conn.execute("DELETE FROM patterns")
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "✅ সব ডেটা মুছে গেছে"})

# Stats summary
@app.route("/stats", methods=["GET"])
def stats():
    multipliers = engine.get_all_multipliers()
    if not multipliers:
        return jsonify({"message": "কোনো ডেটা নেই"})

    categories = engine.get_categories(multipliers)
    counts = Counter(categories)
    total = len(multipliers)

    return jsonify({
        "total_rounds": total,
        "average": round(sum(multipliers)/total, 2),
        "max": max(multipliers),
        "min": min(multipliers),
        "distribution": {
            "LOW (< 2x)":   f"{counts.get('LOW',0)} রাউন্ড ({round(counts.get('LOW',0)/total*100,1)}%)",
            "MID (2x-5x)":  f"{counts.get('MID',0)} রাউন্ড ({round(counts.get('MID',0)/total*100,1)}%)",
            "HIGH (5x-10x)":f"{counts.get('HIGH',0)} রাউন্ড ({round(counts.get('HIGH',0)/total*100,1)}%)",
            "MEGA (10x+)":  f"{counts.get('MEGA',0)} রাউন্ড ({round(counts.get('MEGA',0)/total*100,1)}%)",
        }
    })

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
