(() => {
  'use strict';
  if (window.__mpVisualViewport) return;
  window.__mpVisualViewport = true;
  const root = document.documentElement;
  let queued = false;
  const apply = () => {
    queued = false;
    const viewport = window.visualViewport;
    root.style.setProperty('--mp-visible-height', `${viewport ? viewport.height : window.innerHeight}px`);
    root.style.setProperty('--mp-visible-offset', `${viewport ? viewport.offsetTop : 0}px`);
  };
  const schedule = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(apply);
  };
  if (window.visualViewport) {
    visualViewport.addEventListener('resize', schedule);
    visualViewport.addEventListener('scroll', schedule);
  }
  addEventListener('resize', schedule);
  apply();
})();
