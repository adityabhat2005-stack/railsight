import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ml_crowd import predictor

app = FastAPI(title="RailSight Operational Intelligence API")

DATABASE_URL = os.getenv("DATABASE_URL")  # Set this in Render Environment Variables

def get_db():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def add_minutes_to_time(t_obj, mins: int):
    dt = datetime.combine(datetime.today(), t_obj) + timedelta(minutes=mins)
    return dt.time()

def round_irctc_fare(raw_fare: float) -> float:
    # Indian Railways UTS rounds unreserved fares to nearest ₹5
    return float(max(10, round(raw_fare / 5.0) * 5))

@app.get("/api/stations")
def list_stations():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT station_code, station_name, corridor_km FROM Stations ORDER BY corridor_km ASC;")
            return cur.fetchall()
    finally:
        conn.close()

@app.get("/api/trains")
def get_corridor_trains(
    source: str = Query("MAQ", description="IRCTC Station Code e.g. MAQ, MAJN"),
    dest: str = Query("CLT", description="IRCTC Station Code e.g. CLT, CAN"),
    window_hours: int = Query(24, description="3 for 3-hour window, 24 for full day"),
    day_of_week: int | None = Query(None, description="0=Mon..6=Sun (defaults to today IST)")
):
    src_code = source.strip().upper()
    dst_code = dest.strip().upper()

    if src_code == dst_code:
        raise HTTPException(status_code=400, detail="Source and Destination cannot be the same station.")

    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    dow = day_of_week if day_of_week is not None else now_ist.weekday()

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Validate stations
            cur.execute("SELECT * FROM Stations WHERE station_code IN (%s, %s);", (src_code, dst_code))
            st_rows = {r["station_code"]: r for r in cur.fetchall()}
            if src_code not in st_rows or dst_code not in st_rows:
                raise HTTPException(status_code=404, detail="Invalid IRCTC station code.")

            distance_km = abs(float(st_rows[dst_code]["corridor_km"]) - float(st_rows[src_code]["corridor_km"]))

            # Fetch valid unreserved trains stopping at both source and dest in sequence
            cur.execute("""
                SELECT
                    tm.train_no, tm.train_name, tm.delay_minutes, tm.live_status_note,
                    tc.category_id, tc.category_name, tc.rake_badge,
                    tc.base_fare_per_km, tc.min_fare, tc.surcharge,
                    tc.alert_level, tc.advisory_text,
                    s1.scheduled_time AS src_sched, s1.stop_order AS src_order,
                    s2.scheduled_time AS dst_sched, s2.stop_order AS dst_order
                FROM Train_Master tm
                JOIN Train_Category tc ON tm.category_id = tc.category_id
                JOIN Train_Stops s1 ON tm.train_no = s1.train_no AND s1.station_code = %s
                JOIN Train_Stops s2 ON tm.train_no = s2.train_no AND s2.station_code = %s
                WHERE tc.is_unreserved_allowed = TRUE
                  AND s1.stop_order < s2.stop_order
                ORDER BY s1.scheduled_time ASC;
            """, (src_code, dst_code))
            trains = cur.fetchall()

            results = []
            for tr in trains:
                actual_dep = add_minutes_to_time(tr["src_sched"], tr["delay_minutes"])
                actual_arr = add_minutes_to_time(tr["dst_sched"], tr["delay_minutes"])

                # 3-Hour Window Filter if requested
                if window_hours == 3:
                    now_mins = now_ist.hour * 60 + now_ist.minute
                    dep_mins = actual_dep.hour * 60 + actual_dep.minute
                    diff = (dep_mins - now_mins) % (24 * 60)
                    if diff > 180:
                        continue

                # Fetch intermediate route timeline for this train
                cur.execute("""
                    SELECT station_code, scheduled_time, stop_order
                    FROM Train_Stops
                    WHERE train_no = %s AND stop_order BETWEEN %s AND %s
                    ORDER BY stop_order ASC;
                """, (tr["train_no"], tr["src_order"], tr["dst_order"]))
                stops = cur.fetchall()

                timeline = []
                for idx, st in enumerate(stops):
                    st_actual = add_minutes_to_time(st["scheduled_time"], tr["delay_minutes"])
                    timeline.append({
                        "station_code": st["station_code"],
                        "time": st_actual.strftime("%H:%M"),
                        "is_endpoint": idx == 0 or idx == len(stops) - 1
                    })

                # Compute Dynamic Segment Fare
                raw_fare = max(float(tr["min_fare"]), distance_km * float(tr["base_fare_per_km"])) + float(tr["surcharge"])
                uts_fare = round_irctc_fare(raw_fare)

                # Run Random Forest ML Crowd Prediction
                crowd = predictor.predict(
                    hour=actual_dep.hour,
                    day_of_week=dow,
                    category_id=tr["category_id"],
                    distance_km=distance_km
                )

                results.append({
                    "train_no": tr["train_no"],
                    "train_name": tr["train_name"],
                    "category_name": tr["category_name"],
                    "rake_badge": tr["rake_badge"],
                    "scheduled_dep": tr["src_sched"].strftime("%H:%M"),
                    "actual_dep": actual_dep.strftime("%H:%M"),
                    "actual_arr": actual_arr.strftime("%H:%M"),
                    "delay_minutes": tr["delay_minutes"],
                    "live_status_note": tr["live_status_note"],
                    "distance_km": round(distance_km, 1),
                    "uts_fare": uts_fare,
                    "alert_level": tr["alert_level"],
                    "advisory_text": tr["advisory_text"],
                    "crowd": crowd,
                    "timeline": timeline
                })

            return {
                "source": st_rows[src_code],
                "dest": st_rows[dst_code],
                "distance_km": round(distance_km, 1),
                "server_time_ist": now_ist.strftime("%I:%M:%S %p"),
                "count": len(results),
                "trains": results
            }
    finally:
        conn.close()

class DelayUpdate(BaseModel):
    train_no: str
    delay_minutes: int

@app.post("/api/simulate-delay")
def update_delay(payload: DelayUpdate):
    """Demo endpoint to simulate live train delays during viva/review"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            note = f"Delayed by {payload.delay_minutes} mins" if payload.delay_minutes > 0 else "Running on Schedule"
            cur.execute(
                "UPDATE Train_Master SET delay_minutes = %s, live_status_note = %s WHERE train_no = %s;",
                (payload.delay_minutes, note, payload.train_no)
            )
            conn.commit()
            return {"status": "updated", "train_no": payload.train_no, "delay_minutes": payload.delay_minutes}
    finally:
        conn.close()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")
