// Shared vocabulary with the Python agent. These mirror indent/domain/fields.py
// and indent/domain/confidence.py; the agent test-suite asserts they stay in step.

export const STATE_TOPIC = "indent-state";
export const EDIT_TOPIC = "operator-edit";

export const FIELD_GROUPS = [
  { title: "Route", fields: [
    ["pickupLocation", "Pickup location"],
    ["deliveryLocation", "Delivery location"],
  ]},
  { title: "Cargo", fields: [
    ["material", "Material"],
    ["quantity", "Quantity"],
    ["vehicleType", "Vehicle type"],
  ]},
  { title: "Schedule", fields: [
    ["pickupDate", "Pickup date"],
    ["deliveryDate", "Delivery date"],
  ]},
  { title: "Terms", fields: [["procurementType", "Procurement type"]] },
];

export const ALL_FIELDS = FIELD_GROUPS.flatMap((g) => g.fields);

export const CONF_LABEL = {
  1: "guessed", 2: "heard", 3: "extracted", 4: "confirmed", 5: "edited",
};

export const CONF_EXPLAIN = {
  1: "Heuristic — a label was heard but the place was not recognised.",
  2: "Matched a known term in the caller's own speech.",
  3: "The model extracted this from the conversation.",
  4: "The caller explicitly confirmed this value.",
  5: "You typed this. Nothing automatic can overwrite it.",
};

export const SOURCE_LABEL = {
  llm: "model extraction",
  speech: "caller's speech",
  operator: "your edit",
  validation: "validation",
};

// Thresholds for colouring response latency.
export const LATENCY_GOOD = 900;
export const LATENCY_WARN = 1800;

export const STATE_LABEL = {
  idle: "Idle", connecting: "Connecting", listening: "Listening",
  thinking: "Thinking", speaking: "Speaking",
};
