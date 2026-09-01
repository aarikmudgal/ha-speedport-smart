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

function detail(open, summary = focusable(), detailId = undefined) {
  return {
    dataset: detailId === undefined ? {} : { detailId },
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
  adminRefresh = [],
  views = [],
}) {
  const matches = {
    details,
    "[data-control]": controls,
    "[data-more-info]": moreInfo,
    "[data-router]": routers,
    "[data-refresh]": refresh,
    "[data-admin-refresh]": adminRefresh,
    "[data-view]": views,
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

test("stable detail identity survives reordered nested administration sections", () => {
  const internetSummary = focusable();
  const networkSummary = focusable();
  const state = captureRenderState(
    root({
      activeElement: networkSummary,
      details: [
        detail(true, internetSummary, "admin-area:internet"),
        detail(false, networkSummary, "admin-area:network"),
      ],
    }),
  );
  const system = detail(true, focusable(), "admin-area:system");
  const network = detail(true, focusable(), "admin-area:network");
  const internet = detail(false, focusable(), "admin-area:internet");
  const newRoot = root({ details: [system, network, internet] });

  restoreDetailsState(newRoot, state);

  assert.equal(system.open, true, "new stable section keeps its default state");
  assert.equal(network.open, false);
  assert.equal(internet.open, true);
  assert.equal(restoreFocusState(newRoot, state), true);
  assert.equal(network.querySelector("summary").focusCount, 1);
});

test("administrator refresh focus uses its stable data identity", () => {
  const previous = focusable({ adminRefresh: "" });
  const state = captureRenderState(root({ activeElement: previous }));
  const current = focusable({ adminRefresh: "" });

  assert.equal(
    restoreFocusState(root({ adminRefresh: [current] }), state),
    true,
  );
  assert.equal(current.focusCount, 1);
});

test("view switch restores focus to the selected view button", () => {
  const previous = focusable({ view: "administration" });
  const state = captureRenderState(root({ activeElement: previous }));
  const dashboard = focusable({ view: "dashboard" });
  const administration = focusable({ view: "administration" });

  assert.equal(
    restoreFocusState(root({ views: [dashboard, administration] }), state),
    true,
  );
  assert.equal(dashboard.focusCount, 0);
  assert.equal(administration.focusCount, 1);
});
