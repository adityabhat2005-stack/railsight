import os
import random
import string
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ml_crowd import predictor

app = FastAPI(title="RailSight IRCTC-Style Operational & Booking Portal")

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def add_minutes_to_time(t_obj, mins: int):
    dt = datetime.combine(datetime.today(), t_obj) + timedelta(minutes=mins)
    return dt.time()

def round_irctc_fare(raw_fare: float) -> float:
    return float(max(10, round(raw_fare / 5.0) * 5))

def generate_uts_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "X" + "".join(random.choices(chars, k=9))

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
    source: str = Query("MJS"),
    dest: str = Query("KZE"),
    window_hours: int = Query(24),
    day_of_week: int | None = Query(None)
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
            cur.execute("SELECT * FROM Stations WHERE station_code IN (%s, %s);", (src_code, dst_code))
            st_rows = {r.get("station_code"): r for r in cur.fetchall()}
            if src_code not in st_rows or dst_code not in st_rows:
                raise HTTPException(status_code=404, detail="Invalid IRCTC station code.")

            src_st = st_rows.get(src_code)
            dst_st = st_rows.get(dst_code)
            distance_km = abs(float(dst_st.get("corridor_km")) - float(src_st.get("corridor_km")))

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
                actual_dep = add_minutes_to_time(tr.get("src_sched"), tr.get("delay_minutes"))
                actual_arr = add_minutes_to_time(tr.get("dst_sched"), tr.get("delay_minutes"))

                if window_hours == 3:
                    now_mins = now_ist.hour * 60 + now_ist.minute
                    dep_mins = actual_dep.hour * 60 + actual_dep.minute
                    diff = (dep_mins - now_mins) % (24 * 60)
                    if diff > 180:
                        continue

                cur.execute("""
                    SELECT station_code, scheduled_time, stop_order
                    FROM Train_Stops
                    WHERE train_no = %s AND stop_order BETWEEN %s AND %s
                    ORDER BY stop_order ASC;
                """, (tr.get("train_no"), tr.get("src_order"), tr.get("dst_order")))
                stops = cur.fetchall()

                timeline = []
                for idx, st in enumerate(stops):
                    st_actual = add_minutes_to_time(st.get("scheduled_time"), tr.get("delay_minutes"))
                    timeline.append({
                        "station_code": st.get("station_code"),
                        "time": st_actual.strftime("%H:%M"),
                        "is_endpoint": idx == 0 or idx == len(stops) - 1
                    })

                raw_fare = max(float(tr.get("min_fare")), distance_km * float(tr.get("base_fare_per_km"))) + float(tr.get("surcharge"))
                uts_fare = round_irctc_fare(raw_fare)

                crowd = predictor.predict(
                    hour=actual_dep.hour,
                    day_of_week=dow,
                    category_id=tr.get("category_id"),
                    distance_km=distance_km
                )

                results.append({
                    "train_no": tr.get("train_no"),
                    "train_name": tr.get("train_name"),
                    "category_id": tr.get("category_id"),
                    "category_name": tr.get("category_name"),
                    "rake_badge": tr.get("rake_badge"),
                    "scheduled_dep": tr.get("src_sched").strftime("%H:%M"),
                    "actual_dep": actual_dep.strftime("%H:%M"),
                    "actual_arr": actual_arr.strftime("%H:%M"),
                    "delay_minutes": tr.get("delay_minutes"),
                    "live_status_note": tr.get("live_status_note"),
                    "distance_km": round(distance_km, 1),
                    "uts_fare": uts_fare,
                    "alert_level": tr.get("alert_level"),
                    "advisory_text": tr.get("advisory_text"),
                    "crowd": crowd,
                    "timeline": timeline
                })

            return {
                "source": src_st,
                "dest": dst_st,
                "distance_km": round(distance_km, 1),
                "server_time_ist": now_ist.strftime("%I:%M:%S %p"),
                "count": len(results),
                "trains": results
            }
    finally:
        conn.close()

class BookingRequest(BaseModel):
    passenger_name: str = Field(..., min_length=2, max_length=100)
    source_code: str
    dest_code: str
    train_no: str
    adults: int = Field(1, ge=1, le=6)
    children: int = Field(0, ge=0, le=6)
    journey_type: str = Field("JOURNEY")  # JOURNEY or RETURN
    payment_mode: str = Field("UPI / QR")

@app.post("/api/book")
def create_ticket_booking(req: BookingRequest):
    src = req.source_code.strip().upper()
    dst = req.dest_code.strip().upper()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM Stations WHERE station_code IN (%s, %s);", (src, dst))
            st_rows = {r.get("station_code"): r for r in cur.fetchall()}
            if src not in st_rows or dst not in st_rows:
                raise HTTPException(status_code=400, detail="Invalid station codes.")

            distance_km = abs(float(st_rows.get(dst).get("corridor_km")) - float(st_rows.get(src).get("corridor_km")))

            cur.execute("""
                SELECT tm.train_no, tm.train_name, tc.category_name,
                       tc.base_fare_per_km, tc.min_fare, tc.surcharge
                FROM Train_Master tm
                JOIN Train_Category tc ON tm.category_id = tc.category_id
                WHERE tm.train_no = %s AND tc.is_unreserved_allowed = TRUE;
            """, (req.train_no,))
            tr = cur.fetchone()
            if not tr:
                raise HTTPException(status_code=404, detail="Selected train not eligible for unreserved booking.")

            base_unit = round_irctc_fare(max(float(tr.get("min_fare")), distance_km * float(tr.get("base_fare_per_km"))) + float(tr.get("surcharge")))
            child_unit = round_irctc_fare(base_unit * 0.5)
            multiplier = 2 if req.journey_type.upper() == "RETURN" else 1
            total_fare = round((base_unit * req.adults + child_unit * req.children) * multiplier, 2)

            uts_no = generate_uts_code()
            cur.execute("""
                INSERT INTO Booked_Tickets
                (uts_number, passenger_name, source_code, dest_code, distance_km, train_no, train_name, tier_name, adults, children, journey_type, total_fare, payment_mode)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (
                uts_no, req.passenger_name.strip().upper(), src, dst, round(distance_km, 1),
                tr.get("train_no"), tr.get("train_name"), tr.get("category_name"),
                req.adults, req.children, req.journey_type.upper(), total_fare, req.payment_mode
            ))
            ticket = cur.fetchone()
            conn.commit()
            return ticket
    finally:
        conn.close()

@app.get("/api/bookings")
def get_bookings():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM Booked_Tickets ORDER BY booked_at DESC LIMIT 25;")
            rows = cur.fetchall()
            for r in rows:
                if r.get("booked_at"):
                    r["booked_at"] = r["booked_at"].strftime("%d-%b-%Y %I:%M %p")
            return rows
    finally:
        conn.close()

@app.post("/api/bookings/{uts_number}/cancel")
def cancel_booking(uts_number: str):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE Booked_Tickets SET status = 'CANCELLED' WHERE uts_number = %s RETURNING uts_number;", (uts_number.upper(),))
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=404, detail="Ticket not found.")
                conn.commit()
                return {"status": "CANCELLED", "uts_number": uts_number.upper()}
    finally:
        conn.close()
        app.mount("/static", StaticFiles(directory="static"), name="static")
        @app.get("/")
def serve_ui():
    return FileResponse("static/index.html")
