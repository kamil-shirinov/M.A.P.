/* The inverse standard normal CDF, because the project's own definition of `z`
   needs it.

   WHICH z. M.A.P.'s scoring records carry `map_pit` and `map_sigma` but NOT the
   forecast mean, and the two obvious standardisations are not the same number:

     z = realised_return / map_sigma     ignores where the forecast was centred
     z = Phi^-1(map_pit)                 = (realised - mean) / sigma

   The pre-registration on `ad71b13` (git note record 14) names the second —
   "using the same z = Phi^-1(PIT)" — and it is the one the published tail counts
   were made with. On the 175 clean/dev items the two give 13 and 11 exceedances
   over 2.5; only the second reproduces the 11 (7 blocks) and 7 (5 blocks) in the
   record. The first is a different statistic, not a shortcut to this one.

   ACKLAM'S RATIONAL APPROXIMATION. There is no erf in JavaScript and no
   dependency to reach for. Acklam's is accurate to a relative 1.15e-9 across the
   whole open interval, which is four orders of magnitude finer than any
   threshold this page compares against (2.5 and 3.0), and it needs no iteration.
   A Halley refinement step would need erfc, which is the thing that is missing. */

const A = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
           1.383577518672690e2, -3.066479806614716e1, 2.506628277459239];
const B = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
           6.680131188771972e1, -1.328068155288572e1];
const C = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
           -2.549732539343734, 4.374664141464968, 2.938163982698783];
const D = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
           3.754408661907416];

/* Below and above these the central rational form loses accuracy and the tail
   form takes over. Acklam's own break points, not tuned here. */
const LOW = 0.02425;
const HIGH = 1 - LOW;

export function inverseNormalCdf(p) {
  if (!(p > 0 && p < 1)) {
    // Not clamped to a large finite z: a PIT of exactly 0 or 1 means the outcome
    // fell outside the representable forecast, and a made-up 8.2 would be counted
    // in a tail bucket as though it were measured.
    throw new RangeError(`PIT must be strictly inside (0, 1); got ${p}`);
  }
  if (p < LOW) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5]) /
           ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
  }
  if (p > HIGH) {
    const q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((C[0] * q + C[1]) * q + C[2]) * q + C[3]) * q + C[4]) * q + C[5]) /
            ((((D[0] * q + D[1]) * q + D[2]) * q + D[3]) * q + 1);
  }
  const q = p - 0.5;
  const r = q * q;
  return (((((A[0] * r + A[1]) * r + A[2]) * r + A[3]) * r + A[4]) * r + A[5]) * q /
         (((((B[0] * r + B[1]) * r + B[2]) * r + B[3]) * r + B[4]) * r + 1);
}
