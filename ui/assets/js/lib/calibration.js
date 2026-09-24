/* The single source of truth for what "calibrated" means. Nothing else decides. */

export const CALIBRATED_HORIZONS = [5];
export const HORIZONS = [1, 5, 10, 21];

export function isCalibrated(horizonDays) {
  return CALIBRATED_HORIZONS.includes(horizonDays);
}

export function calibrationState(horizonDays) {
  return isCalibrated(horizonDays) ? "calibrated" : "uncalibrated";
}

/** What the interface says about itself at this horizon. Deliberately states
    the limit rather than projecting confidence. */
export function calibrationNote(horizonDays) {
  if (isCalibrated(horizonDays)) {
    return {
      headline: "Five sessions is the calibrated horizon.",
      detail:
        "Band width has been scored against realised outcomes on the development " +
        "half of the corpus. The measured coverage is reported separately, corpus-wide.",
    };
  }
  return {
    headline: `${horizonDays} sessions carries no measured reliability.`,
    detail:
      "This is not a separate forecast. It is the five-session scenarios extrapolated — " +
      "return scaled linearly, volatility by the square root of time — and that " +
      "extrapolation has never been scored. The band width here is arithmetic, not evidence.",
  };
}
