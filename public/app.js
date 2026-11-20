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
    if (!response.ok) throw new Error();

    const stations = await response.json();
    addStationOptions(sourceSelect, stations, "Choose a source");
    addStationOptions(destinationSelect, stations, "Choose a destination");

    if (!stations.length) {
      showNotice("No stations are in the database yet.");
    }
  } catch {
    showNotice("Could not load stations. Please try again.");
  }
}

function createTextElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
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

  card.append(
    createTextElement("h3", "", train.train_name),
    createTextElement("p", "train-number", `Train ${train.train_no}`),
    createTextElement("p", "train-time", formatTime(train.scheduled_departure)),
    createTextElement(
      "p",
      "",
      `${train.source_station} → ${train.dest_station}`
    )
  );

  const badges = document.createElement("div");
  badges.className = "badges";
  badges.append(
    createTextElement("span", "badge", train.service_category)
  );

  if (train.specialty) {
    badges.append(createTextElement("span", "badge specialty", "Specialty train"));
  }

  card.append(badges);

  const accessClass = train.unreserved_access
    ? "advisory advisory-yellow"
    : "advisory advisory-red";

  const accessText = train.unreserved_access
    ? "Unreserved access is marked in the demo data."
    : "Unreserved access is not marked for this demo train.";

  card.append(
    createTextElement("p", accessClass, accessText),
    createTextElement("p", "ticket-advisory", train.ticket_advisory),
    createTextElement(
      "p",
      "external-booking-note",
      "To book, use an official railway booking channel. RailSight does not book or issue tickets."
    )
  );

  return card;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  results.replaceChildren();

  const source = sourceSelect.value;
  const destination = destinationSelect.value;

  if (!source || !destination || source === destination) {
    showNotice("Choose two different stations.");
    return;
  }

  showNotice("Searching schedules…");

  try {
    const params = new URLSearchParams({ source, destination });
    const response = await fetch(`/api/schedules?${params}`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Search failed.");
    }

    if (!data.length) {
      showNotice("No matching trains found in the next three hours.");
      return;
    }

    showNotice(`${data.length} train(s) found.`);
    for (const train of data) {
      results.append(makeCard(train));
    }
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

if (localStorage.getItem("railsight-theme") === "light") {
  document.body.classList.add("light");
}

themeButton.addEventListener("click", () => {
  document.body.classList.toggle("light");
  localStorage.setItem(
    "railsight-theme",
    document.body.classList.contains("light") ? "light" : "dark"
  );
});

loadStations();
