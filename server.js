const express = require("express");
const { Pool } = require("pg");
const path = require("path");

const app = express();
const port = process.env.PORT || 3000;

if (!process.env.DATABASE_URL) {
  console.error("Missing DATABASE_URL environment variable.");
  process.exit(1);
}

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
  max: 5,
  idleTimeoutMillis: 10000,
  connectionTimeoutMillis: 10000
});

app.use(express.static(path.join(__dirname, "public")));

app.get("/api/stations", async (_req, res) => {
  try {
    const result = await pool.query(`
      SELECT station_code, station_name
      FROM stations
      ORDER BY station_name
    `);
    res.set("Cache-Control", "public, max-age=300");
    res.json(result.rows);
  } catch (error) {
    console.error("Station query failed:", error.message);
    res.status(500).json({ error: "Could not load stations." });
  }
});

app.get("/api/schedules", async (req, res) => {
  const source = String(req.query.source || "").trim().toUpperCase();
  const destination = String(req.query.destination || "").trim().toUpperCase();

  if (
    !/^[A-Z0-9]{2,10}$/.test(source) ||
    !/^[A-Z0-9]{2,10}$/.test(destination) ||
    source === destination
  ) {
    return res.status(400).json({
      error: "Choose two different valid stations."
    });
  }

  try {
    const result = await pool.query(
      `
      SELECT
        t.train_no,
        t.train_name,
        s.source_station,
        s.dest_station,
        s.scheduled_departure,
        s.delay_minutes,
        c.category_name AS service_category,
        t.specialty,
        t.unreserved_access,
        t.ticket_advisory
      FROM schedules s
      JOIN trains t ON t.train_no = s.train_no
      JOIN train_categories c ON c.category_id = t.category_id
      WHERE s.source_station = $1
        AND s.dest_station = $2
        AND s.scheduled_departure >= NOW()
        AND s.scheduled_departure < NOW() + INTERVAL '3 hours'
        AND t.unreserved_access = TRUE
      ORDER BY s.scheduled_departure ASC
      LIMIT 100
      `,
      [source, destination]
    );

    res.set("Cache-Control", "no-store");
    res.json(result.rows);
  } catch (error) {
    console.error("Schedule query failed:", error.message);
    res.status(500).json({ error: "Could not load schedules." });
  }
});

app.get("/health", (_req, res) => res.json({ ok: true }));

app.listen(port, "0.0.0.0", () => {
  console.log(`RailSight listening on port ${port}`);
});
