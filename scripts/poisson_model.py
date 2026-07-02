"""基础Poisson比分矩阵.
用于Maher类模型的最小落地骨架。生产版需要参数估计与联赛分层。"""

from __future__ import annotations

from math import exp, factorial


def poisson_pmf(k: int, lam: float) -> float:
    return exp(-lam) * (lam**k) / factorial(k)


def score_matrix(lambda_home: float, lambda_away: float, max_goals: int = 7) -> dict[str, float]:
    matrix = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            matrix[f"{h}:{a}"] = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
    # 将大于max_goals的尾部概率留给后续"其它"选项处理；这里先归一化便于玩法推导。
    s = sum(matrix.values())
    return {k: v / s for k, v in matrix.items()}


def derive_1x2(matrix: dict[str, float]) -> dict[str, float]:
    home = draw = away = 0.0
    for score, p in matrix.items():
        h, a = map(int, score.split(":"))
        if h > a:
            home += p
        elif h == a:
            draw += p
        else:
            away += p
    return {"3": home, "1": draw, "0": away}


def derive_total_goals(matrix: dict[str, float]) -> dict[str, float]:
    out = {str(i): 0.0 for i in range(7)}
    out["7+"] = 0.0
    for score, p in matrix.items():
        h, a = map(int, score.split(":"))
        total = h + a
        if total >= 7:
            out["7+"] += p
        else:
            out[str(total)] += p
    return out


def estimate_lambdas_from_odds(
    home_prob: float, draw_prob: float, away_prob: float, max_goals: int = 7
) -> tuple[float, float]:
    """Reverse-engineer Poisson lambdas from 1x2 probabilities.

    Uses scipy.optimize.minimize to find (lambda_home, lambda_away) whose
    score matrix derive_1x2() best matches the given target probabilities.

    This is the bridge from odds-implied probabilities to Poisson score
    distributions — enabling score matrix and total goals derivation
    without historical match data for parameter estimation.

    Args:
        home_prob: Target home win probability (e.g., 0.45)
        draw_prob: Target draw probability
        away_prob: Target away win probability
        max_goals: Maximum goals per team for the score matrix

    Returns:
        (lambda_home, lambda_away) tuple
    """
    target = {"3": home_prob, "1": draw_prob, "0": away_prob}

    def loss(lam: tuple[float, float]) -> float:
        """MSE between derived 1x2 and target probabilities."""
        lam_h, lam_a = lam[0], lam[1]
        if lam_h <= 0 or lam_a <= 0:
            return 1e9  # penalty for invalid lambdas
        matrix = score_matrix(lam_h, lam_a, max_goals)
        derived = derive_1x2(matrix)
        mse = sum((derived[k] - target[k]) ** 2 for k in target)
        return mse

    # Initial guess: lambdas ~= -ln(1 - prob) scaled by typical goal rates
    # A typical match has ~2.6 total goals. Use target probs as weights.
    init_h = 1.0 + home_prob * 2.0
    init_a = 1.0 + away_prob * 2.0

    try:
        from scipy.optimize import minimize

        result = minimize(
            loss,
            x0=[init_h, init_a],
            bounds=[(0.1, 5.0), (0.1, 5.0)],
            method="L-BFGS-B",
            options={"maxiter": 200},
        )
        if result.success or result.fun < 1e-6:
            return (float(result.x[0]), float(result.x[1]))
    except ImportError:
        pass

    # Fallback: simple grid search if scipy is unavailable
    best_loss = float("inf")
    best_lam = (init_h, init_a)
    for lh in [x / 10.0 for x in range(5, 50)]:
        for la in [x / 10.0 for x in range(5, 50)]:
            loss_val = loss((lh, la))
            if loss_val < best_loss:
                best_loss = loss_val
                best_lam = (lh, la)
    return best_lam


if __name__ == "__main__":
    m = score_matrix(1.45, 1.10)
    print(derive_1x2(m))
    print(derive_total_goals(m))
    # Test lambda estimation
    lam_h, lam_a = estimate_lambdas_from_odds(0.476, 0.283, 0.241)
    print(f"Estimated lambdas: home={lam_h:.3f}, away={lam_a:.3f}")
    test_m = score_matrix(lam_h, lam_a)
    print(f"Recovered 1x2: {derive_1x2(test_m)}")
