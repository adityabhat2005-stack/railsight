const sourceSelect = document.querySelector("#source");
const destinationSelect = document.querySelector("#destination");
const form = document.querySelector("#searchForm");
const results = document.querySelector("#results");
const notice = document.querySelector("#notice");

function showNotice(message) {
  notice.textContent = message;
}

function addStationOptions(select, stations, placeholder) {
  select.replaceChildren(new Option(placeholder, ""));
  for (const station of stations) {
    const label = `${station.station_name} (${station.station_code})`;
    select.add(new Option(label, station.station_code));
  }
}

async function loadStations() {
  try {
    const response = await fetch("/api/stations");
    if (!response.ok) throw new Error("Station request failed");
    const stations = await response.json();

    addStationOptions(sourceSelect, stations, "Choose a source");
    addStationOptions(destinationSelect, stations, "Choose a destination");

    if (!stations.length) {
      showNotice("No stations have been added to the database yet.");
    }
  } catch {
    showNotice("Could not load stations. Please try again later.");
  }
}

function formatTime(value) {
  return new Intl.DateTimeFormat([], {
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function makeCard(train) {
  const card = document.createElement("article");
  card.className = "train-card";

  const title = document.createElement("h3");
  title.textContent = `${train.train_name} · ${train.train_no}`;

  const time = document.createElement("p");
  time.className = "train-time";
  time.textContent = formatTime(train.scheduled_departure);

  const route = document.createElement("p");
  route.textContent = `${train.source_station} → ${train.dest_station}`;

  const category = document.createElement("p");
  category.textContent = train.specialty
    ? `Specialty service · ${train.category_name}`
    : `Unreserved-accessible category · ${train.category_name}`;

  const advisory = document.createElement("p");
  advisory.className = "advisory advisory-yellow";
  advisory.textContent =
    "Check current ticket requirements and coach availability before boarding.";

  card.append(title, time, route, category, advisory);
  return card;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  results.replaceChildren();

  const source = sourceSelect.value;
  const destination = destinationSelect.value;

  if (!source || !destination || source === destination) {
    showNotice("Select two different stations.");
    return;
  }

  showNotice("Searching schedules…");

  try {
    const params = new URLSearchParams({ source, destination });
    const response = await fetch(`/api/schedules?${params}`);
    const data = await response.json();

    if (!response.ok) throw new Error(data.error || "Search failed");

    if (!data.length) {
      showNotice("No matching trains found in the next three hours.");
      return;
    }

    showNotice(`${data.length} train(s) found.`);
    for (const train of data) results.append(makeCard(train));
  } catch (error) {
    showNotice(error.message || "Could not load schedules.");
  }
});

document.querySelector("#swapButton").addEventListener("click", () => {
  const oldSource = sourceSelect.value;
  sourceSelect.value = destinationSelect.value;
  destinationSelect.value = oldSource;
});

const themeButton = document.querySelector("#themeToggle");
const savedTheme = localStorage.getItem("railsight-theme");
if (savedTheme === "light") document.body.classList.add("light");

themeButton.addEventListener("click", () => {
  document.body.classList.toggle("light");
  localStorage.setItem(
    "railsight-theme",
    document.body.classList.contains("light") ? "light" : "dark"
  );
});

loadStations();
