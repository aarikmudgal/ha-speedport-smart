import assert from "node:assert/strict";
import test from "node:test";

import {
  aggregateAvailability,
  entityDisplayName,
  entityAvailability,
} from "../../custom_components/speedport_smart/frontend/entity-state.js";

test("unknown non-button entities are neutral, not healthy", () => {
  assert.equal(
    entityAvailability({ domain: "sensor" }, { state: "unknown" }),
    "unknown",
  );
  assert.equal(
    entityAvailability({ domain: "device_tracker" }, { state: "unknown" }),
    "unknown",
  );
  assert.equal(
    entityAvailability({ domain: "button" }, { state: "unknown" }),
    "available",
  );
  assert.equal(
    entityAvailability({ domain: "sensor" }, { state: "unavailable" }),
    "unavailable",
  );
});

test("child availability requires at least one actually available entity", () => {
  assert.equal(aggregateAvailability(["unavailable", "unknown"]), "unknown");
  assert.equal(aggregateAvailability(["unknown", "available"]), "available");
  assert.equal(aggregateAvailability(["unavailable"]), "unavailable");
});

test("port forwarding controls retain each rule's distinct target name", () => {
  const meta = {
    domain: "switch",
    translation_key: "port_forward_rule",
  };
  const https = entityDisplayName(
    meta,
    { attributes: { friendly_name: "HTTPS server" } },
    "Port forwarding rule",
    "Fallback",
  );
  const game = entityDisplayName(
    meta,
    { attributes: { friendly_name: "Game server" } },
    "Port forwarding rule",
    "Fallback",
  );

  assert.equal(https, "HTTPS server");
  assert.equal(game, "Game server");
  assert.notEqual(https, game);
});
