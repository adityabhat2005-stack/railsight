card.append(
  createTextElement(
    "p",
    `crowd crowd-${train.crowd_level.toLowerCase()}`,
    `Demo crowd estimate: ${train.crowd_level}`
  ),
  createTextElement(
    "p",
    "crowd-detail",
    `Based on ${train.crowd_weekday} · ${train.crowd_time_band} · ` +
      `Crowd rank ${train.crowd_rank} of ${train.crowd_total}`
  ),
  createTextElement(
    "p",
    "crowd-note",
    "General demo estimate only—not live occupancy or a guarantee."
  )
);
