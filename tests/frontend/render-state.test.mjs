import assert from "node:assert/strict";
import test from "node:test";

import {
  captureRenderState,
  restoreDetailsState,
  restoreFocusState,
} from "../../custom_components/speedport_smart/frontend/render-state.js";

function focusable(dataset = {}, options = {}) {
  return {
    dataset,
    disabled: Boolean(options.disabled),
    focusCount: 0,
    focus() {
      this.focusCount += 1;
    },
  };
}

function detail(open, summary = focusable()) {
  return {
    open,
    querySelector(selector) {
      return selector === "summary" ? summary : undefined;
    },
  };
}

function root({
  activeElement,
  details = [],
  controls = [],
  moreInfo = [],
  routers = [],
  refresh = [],
}) {
  const matches = {
    details,
    "[data-control]": controls,
    "[data-more-info]": moreInfo,
    "[data-router]": routers,
    "[data-refresh]": refresh,
  };
  return {
    activeElement,
    querySelectorAll(selector) {
      return matches[selector] || [];
    },
  };
}

test("routine render restores active control by exact data identity", () => {
  const oldControl = focusable({ control: 'switch.router["unsafe"]' });
  const state = captureRenderState(root({ activeElement: oldControl }));
  const wrong = focusable({ control: "switch.other" });
  const restored = focusable({ control: 'switch.router["unsafe"]' });

  assert.equal(
    restoreFocusState(root({ controls: [wrong, restored] }), state),
    true,
  );
  assert.equal(wrong.focusCount, 0);
  assert.equal(restored.focusCount, 1);
});

test("disabled or removed control restores focus to matching entity button", () => {
  const entityId = "switch.speedport_wifi";
  const state = captureRenderState(
    root({ activeElement: focusable({ control: entityId }) }),
  );
  const disabled = focusable({ control: entityId }, { disabled: true });
  const entity = focusable({ moreInfo: entityId });

  assert.equal(
    restoreFocusState(
      root({ controls: [disabled], moreInfo: [entity] }),
      state,
    ),
    true,
  );
  assert.equal(disabled.focusCount, 0);
  assert.equal(entity.focusCount, 1);
});

test("every details state and focused summary survive replacement", () => {
  const oldSummaries = [focusable(), focusable(), focusable()];
  const state = captureRenderState(
    root({
      activeElement: oldSummaries[1],
      details: [
        detail(true, oldSummaries[0]),
        detail(false, oldSummaries[1]),
        detail(true, oldSummaries[2]),
      ],
    }),
  );
  const newSummaries = [focusable(), focusable(), focusable()];
  const newDetails = newSummaries.map((summary) => detail(false, summary));
  const newRoot = root({ details: newDetails });

  restoreDetailsState(newRoot, state);
  assert.deepEqual(newDetails.map((item) => item.open), [true, false, true]);
  assert.equal(restoreFocusState(newRoot, state), true);
  assert.deepEqual(newSummaries.map((item) => item.focusCount), [0, 1, 0]);
});
