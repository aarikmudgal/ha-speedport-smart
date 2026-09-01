const FOCUS_DATA_KEYS = [
  "adminRefresh",
  "control",
  "moreInfo",
  "router",
  "refresh",
];

function detailsElements(root) {
  return [...(root?.querySelectorAll?.("details") || [])];
}

function detailId(detail) {
  const value = detail?.dataset?.detailId;
  return value === undefined ? undefined : String(value);
}

/** Capture interaction state before replacing dashboard shadow DOM. */
export function captureRenderState(root) {
  const details = detailsElements(root);
  const active = root?.activeElement;
  let focus;

  for (const key of FOCUS_DATA_KEYS) {
    if (active?.dataset && Object.hasOwn(active.dataset, key)) {
      focus = { kind: "data", key, value: String(active.dataset[key] ?? "") };
      break;
    }
  }

  if (!focus && active) {
    const detailIndex = details.findIndex(
      (detail) => detail.querySelector?.("summary") === active,
    );
    if (detailIndex !== -1) {
      const stableId = detailId(details[detailIndex]);
      focus = stableId
        ? { kind: "summary", detailId: stableId }
        : { kind: "summary", detailIndex };
    }
  }

  return {
    detailsOpen: details.map((detail) => Boolean(detail.open)),
    detailsOpenById: Object.fromEntries(
      details
        .map((detail) => [detailId(detail), Boolean(detail.open)])
        .filter(([id]) => id),
    ),
    focus,
  };
}

/** Restore expanded/collapsed state without retaining stale DOM references. */
export function restoreDetailsState(root, state) {
  const openStates = state?.detailsOpen;
  const openStatesById = state?.detailsOpenById;
  if (!Array.isArray(openStates) && !openStatesById) return;
  for (const [index, detail] of detailsElements(root).entries()) {
    const stableId = detailId(detail);
    if (stableId && Object.hasOwn(openStatesById || {}, stableId)) {
      detail.open = Boolean(openStatesById[stableId]);
    } else if (
      !stableId &&
      Array.isArray(openStates) &&
      index < openStates.length
    ) {
      detail.open = openStates[index];
    }
  }
}

function dataCandidates(root, key) {
  const selectors = {
    adminRefresh: "[data-admin-refresh]",
    control: "[data-control]",
    moreInfo: "[data-more-info]",
    router: "[data-router]",
    refresh: "[data-refresh]",
  };
  const selector = selectors[key];
  return selector ? [...(root?.querySelectorAll?.(selector) || [])] : [];
}

/** Restore focus by stable data identity, never by interpolating selector text. */
export function restoreFocusState(root, state) {
  const focus = state?.focus;
  if (!focus) return false;

  let target;
  if (focus.kind === "summary") {
    const details = detailsElements(root);
    const detail = focus.detailId
      ? details.find((candidate) => detailId(candidate) === focus.detailId)
      : details[focus.detailIndex];
    target = detail?.querySelector?.("summary");
  } else if (focus.kind === "data") {
    target = dataCandidates(root, focus.key).find(
      (candidate) => String(candidate.dataset?.[focus.key] ?? "") === focus.value,
    );
    if (focus.key === "control" && (!target || target.disabled)) {
      target = dataCandidates(root, "moreInfo").find(
        (candidate) => String(candidate.dataset?.moreInfo ?? "") === focus.value,
      );
    }
  }

  if (!target || target.disabled || typeof target.focus !== "function") {
    return false;
  }
  target.focus();
  return true;
}
