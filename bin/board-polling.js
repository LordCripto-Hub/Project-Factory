(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.createBoardPollCoordinator = api.createBoardPollCoordinator;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function createBoardPollCoordinator(load, apply, onError) {
    const state = {inFlight: false, pending: false, issued: 0, applied: 0};
    return async function requestBoardRefresh() {
      if (state.inFlight) {
        state.pending = true;
        return;
      }
      state.inFlight = true;
      const requestId = ++state.issued;
      try {
        const snapshot = await load();
        if (requestId > state.applied) {
          state.applied = requestId;
          apply(snapshot);
        }
      } catch (error) {
        if (onError) onError(error);
      } finally {
        state.inFlight = false;
        if (state.pending) {
          state.pending = false;
          queueMicrotask(requestBoardRefresh);
        }
      }
    };
  }
  return {createBoardPollCoordinator};
});
