/** Short-lived, connection-owned polling priority. No router requests or storage. */
const FOCUS_TYPE = "speedport_smart/panel/focus";
const RENEW_TYPE = `${FOCUS_TYPE}/renew`;
const RENEW_MS = 15000;
const VIEWS = new Set(["dashboard", "administration"]);
const identityValid = (value) => typeof value === "string" && value.length > 0 && value.length <= 128;
const sameScope = (left, right) => left?.connection === right?.connection &&
  left?.entryId === right?.entryId && left?.userId === right?.userId &&
  left?.view === right?.view && left?.eligible === right?.eligible;

export function createPollingFocusController({setTimer = setTimeout, clearTimer = clearTimeout, isEligible = () => true} = {}) {
  let desired = null;
  let active = null;
  let connection = null;
  let offline = false;
  let failed = false;
  let reacquiresLeft = 1;
  const unsupported = new WeakSet();
  const unsubscribe = (claim) => {
    if (typeof claim.unsubscribe !== "function") return;
    const close = claim.unsubscribe;
    claim.unsubscribe = null;
    try { Promise.resolve(close()).catch(() => {}); } catch { /* The connection may already be closed. */ }
  };
  const stop = () => {
    const claim = active;
    active = null;
    if (!claim) return;
    if (claim.timer !== null) clearTimer(claim.timer);
    claim.timer = null;
    unsubscribe(claim);
  };
  const current = (claim) => active === claim && desired?.eligible === true && isEligible() &&
    desired.connection === claim.connection && !offline && claim.connection.connected !== false;
  const fail = (claim, error) => {
    if (error?.code === "unknown_command") unsupported.add(claim.connection);
    if (active === claim) { failed = true; stop(); }
  };
  const schedule = (claim) => {
    if (!current(claim) || claim.timer !== null || !claim.unsubscribe || claim.subscriptionId === null) return;
    claim.timer = setTimer(async () => {
      claim.timer = null;
      if (!current(claim)) { if (active === claim) stop(); return; }
      try {
        const result = await claim.connection.sendMessagePromise({
          type: RENEW_TYPE, subscription_id: claim.subscriptionId,
        });
        if (!current(claim)) return;
        if (result?.expires_in_seconds !== 45) { fail(claim); return; }
        schedule(claim);
      } catch (error) {
        // An integration reload can retire the lease without replacing HA's
        // connection. Recover once per real activation, never on every renew.
        if (error?.code === "focus_not_found" && current(claim) && reacquiresLeft > 0) {
          reacquiresLeft--; stop(); start();
        } else fail(claim, error);
      }
    }, RENEW_MS);
  };
  const start = () => {
    if (active || failed || !desired?.eligible || !isEligible() || !connection || offline || connection.connected === false ||
        unsupported.has(connection) || typeof connection.subscribeMessage !== "function" ||
        typeof connection.sendMessagePromise !== "function") return;
    const claim = active = {connection, subscriptionId: null, unsubscribe: null, timer: null};
    const receive = (event) => {
      if (!current(claim)) return;
      if (!Number.isSafeInteger(event?.subscription_id) || event.subscription_id <= 0 ||
          event.expires_in_seconds !== 45 || claim.subscriptionId !== null) { fail(claim); return; }
      claim.subscriptionId = event.subscription_id;
      schedule(claim);
    };
    // HA normally replays subscriptions after reconnect. Focus must instead be
    // reclaimed only after rechecking the visible, focused document and scope.
    let pending;
    try {
      pending = connection.subscribeMessage(receive, {
        type: FOCUS_TYPE, entry_id: desired.entryId, view: desired.view,
      }, {resubscribe: false, preCheck: () => current(claim)});
    } catch (error) { fail(claim, error); return; }
    Promise.resolve(pending).then((close) => {
      if (typeof close !== "function") return;
      claim.unsubscribe = close;
      if (!current(claim)) unsubscribe(claim);
      else schedule(claim);
    }).catch((error) => fail(claim, error));
  };
  const disconnected = () => { offline = true; failed = false; stop(); };
  const ready = () => { offline = false; failed = false; reacquiresLeft = 1; stop(); start(); };
  const detach = () => {
    connection?.removeEventListener?.("disconnected", disconnected);
    connection?.removeEventListener?.("ready", ready);
  };
  return {
    update(value) {
      const next = value && identityValid(value.entryId) && identityValid(value.userId) && VIEWS.has(value.view)
        ? {connection: value.connection, entryId: value.entryId, userId: value.userId,
          view: value.view, eligible: value.eligible === true} : null;
      if (sameScope(desired, next)) { start(); return; }
      stop();
      failed = false;
      reacquiresLeft = 1;
      if (connection !== next?.connection) {
        detach();
        connection = next?.connection ?? null;
        offline = connection?.connected === false;
        connection?.addEventListener?.("disconnected", disconnected);
        connection?.addEventListener?.("ready", ready);
      }
      desired = next;
      start();
    },
    dispose() {
      stop(); detach(); desired = null; connection = null; offline = false; failed = false; reacquiresLeft = 1;
    },
  };
}
