export interface JointDistribution {
  p11: number;
  p10: number;
  p01: number;
  p00: number;
  pB: number;
  pAGivenB: number;
  pAGivenNotB: number;
  phi: number;
  mutualInformation: number;
}

export function jointDistribution(
  pA: number,
  pBGivenA: number,
  pBGivenNotA: number,
): JointDistribution {
  const p11 = pA * pBGivenA;
  const p10 = pA * (1 - pBGivenA);
  const p01 = (1 - pA) * pBGivenNotA;
  const p00 = (1 - pA) * (1 - pBGivenNotA);
  const pB = p11 + p01;
  const denominator = Math.sqrt(pA * (1 - pA) * pB * (1 - pB));
  const cells: Array<[number, number, number]> = [
    [p11, pA, pB],
    [p10, pA, 1 - pB],
    [p01, 1 - pA, pB],
    [p00, 1 - pA, 1 - pB],
  ];

  return {
    p11,
    p10,
    p01,
    p00,
    pB,
    pAGivenB: pB === 0 ? 0 : p11 / pB,
    pAGivenNotB: pB === 1 ? 0 : p10 / (1 - pB),
    phi: denominator === 0 ? 0 : (p11 * p00 - p10 * p01) / denominator,
    mutualInformation: cells.reduce(
      (sum, [p, pAMarginal, pBMarginal]) =>
        p === 0 ? sum : sum + p * Math.log2(p / (pAMarginal * pBMarginal)),
      0,
    ),
  };
}
