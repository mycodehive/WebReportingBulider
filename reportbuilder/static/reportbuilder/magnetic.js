/* Coordinates are millimetres; callers convert the screen-pixel tolerance. */
((root) => {
  'use strict';
  function snap(geometry, targets, {threshold, maxWidth, maxHeight, resizing = false}) {
    const result = {...geometry}, guides = [];
    for (const [axis, position, size, limit, minimum] of [
      ['x', 'x_mm', 'width_mm', maxWidth, 2],
      ['y', 'y_mm', 'height_mm', maxHeight, 1],
    ]) {
      const anchors = resizing ? [result[position] + result[size]] :
        [result[position], result[position] + result[size] / 2, result[position] + result[size]];
      let nearest = null;
      for (const target of targets) {
        const lines = [target[position], target[position] + target[size] / 2, target[position] + target[size]];
        for (const line of lines) for (const anchor of anchors) {
          const delta = line - anchor;
          const value = result[resizing ? size : position] + delta;
          const low = resizing ? minimum : 0;
          const high = resizing ? limit - result[position] : limit - result[size];
          if (value < low || value > high || Math.abs(delta) > threshold) continue;
          if (!nearest || Math.abs(delta) < Math.abs(nearest.delta)) nearest = {delta, line, value};
        }
      }
      if (nearest) {
        result[resizing ? size : position] = nearest.value;
        guides.push({axis, position: nearest.line});
      }
    }
    return {geometry: result, guides};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {snap};
  else root.reportMagnet = {snap};
})(globalThis);
