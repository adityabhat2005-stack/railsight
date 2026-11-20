const express = require("express");
const { Pool } = require("pg");
const path = require("path");
const { RandomForestClassifier } = require("ml-random-forest");

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

// Demo labels: 0 = Low, 1 = Moderate, 2 = High.
// These are invented training examples, not measured passenger counts.
function demoCrowdLabel(day, hour) {
  const weekend = day === 0 || day === 6;

  if (weekend && hour >= 10 && hour <= 17) return 2;
  if (!weekend && ((hour >= 6 && hour <= 9) || (hour >= 16 && hour <= 19))) {
    return 2;
  }
  if (hour >= 10 && hour <= 15) return 1;
  if (weekend && hour >= 8 && hour <= 9) return 1;
  return 0;
}

const trainingFeatures = [];
const trainingLabels = [];

for (let day = 0; day < 7; day++) {
  for (let hour = 5; hour <= 23; hour++) {
    // Repeat each synthetic day/hour example to give the demo classifier
    // more training rows. This does not make it real-world crowd data.
    for (let repeat = 0; repeat < 5; repeat++) {
      trainingFeatures.push([day, hour]);
      trainingLabels.push(demoCrowdLabel(day, hour));
    }
  }
}

const crowdModel = new RandomForestClassifier({
  seed: 42,
  maxFeatures: 2,
  replacement: true,
  nEstimators: 30
});

crowdModel.train(trainingFeatures, trainingLabels);

const crowdNames = ["Low", "Moderate", "High"];
const weekdayNumbers = {
  Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6
};

function getIstFeatures(dateValue) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    hour: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date(dateValue));

  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    day: weekdayNumbers[values.weekday],
    hour: Number(values.hour),
    weekday: values.weekday
  };
}

function addCrowdPredictions(rows) {
  const predictions = crowdModel.predict(
    rows.map((row) => {
      const features = getIstFeatures(row.scheduled_departure);
      return [features.day, features.hour];
    })
  );

  const withCrowd = rows.map((row, index) => {
    const features = getIstFeatures(row.scheduled_departure);
    const crowdScore = Number(predictions[index]);

    return {
      ...row,
      crowd_level: crowdNames[crowdScore] || "Moderate",
      crowd_weekday: features.weekday,
      crowd_time_band:
        features.hour < 12 ? "Morning" :
        features.hour < 17 ? "Afternoon" : "Evening",
      crowd_forecast_type: "Synthetic demo estimate",
      crowd_score: crowdScore
    };
  });

  // Rank by expected crowd: lower crowd gets rank 1.
  // Keep the final results in departure-time order.
  const ranked = [...withCrowd].sort(
    (a, b) =>
      a.crowd_score - b.crowd_score ||
      new Date(a.scheduled_departure) - new Date(b.scheduled_departure)
  );

  ranked.forEach((row, index) => {
    row.crowd_rank = index + 1;
    row.crowd_total = ranked.length;
  });

  return withCrowd;
}

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
    res.json(addCrowdPredictions(result.rows));
  } catch (error) {
    console.error("Schedule query failed:", error.message);
    res.status(500).json({ error: "Could not load schedules." });
  }
});

app.get("/health", (_req, res) => res.json({ ok: true }));

app.listen(port, "0.0.0.0", () => {
  console.log(`RailSight listening on port ${port}`);
});
