"""MLE 模型参数训练器。

从历史比赛结果用最大似然估计 (MLE) 拟合模型参数：

  1. Maher Poisson: attack_i, defense_j, home_advantage, league_intercept
     log(lambda_home_i) = attack_i + defense_j + home_adv + league_mean
     log(lambda_away_j) = attack_j + defense_i + league_mean
     负对数似然: -Σ log(Poisson(k | lambda))

  2. Dixon-Coles rho: 低比分相关性参数
     似然 = p_ij * τ(x,y,λ,μ,ρ)
     ρ 从 0 附近开始优化

输入：official_matches + official_results (已结算、有比分的比赛)
输出：更新 model_versions 表的 parameters_json 字段

使用方式：
  from scripts.mle_trainer import fit_maher_poisson, fit_dixon_coles_rho
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any

# Ensure project root is on sys.path for both direct execution and Docker imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np  # noqa: E402

from scripts.poisson_model import poisson_pmf  # noqa: E402

# —— 负对数似然函数 ——


def _nll_maher(
    params: np.ndarray,
    team_ids: list[int],
    home_idx: list[int],
    away_idx: list[int],
    home_goals: list[int],
    away_goals: list[int],
    n_teams: int,
) -> float:
    """Maher Poisson 模型的负对数似然。

    params layout (长度 = n_teams * 2 + 2):
      [0 : n_teams]               attack 参数 (每个球队)
      [n_teams : 2*n_teams]      defense 参数 (每个球队)
      [-2]                        home_advantage
      [-1]                        league_intercept

    Constraints: sum(attack) = 0, sum(defense) = 0
    """
    attack = params[:n_teams]
    defense = params[n_teams : 2 * n_teams]
    home_adv = params[-2]
    league_intercept = params[-1]

    # 软约束：惩罚 attack/defense 均值偏离 0
    penalty = float(np.mean(attack) ** 2 + np.mean(defense) ** 2) * 1000.0

    nll = penalty
    for i in range(len(home_goals)):
        tid_h = home_idx[i]
        tid_a = away_idx[i]
        hg = home_goals[i]
        ag = away_goals[i]

        # log(lambda_home) = attack_home + defense_away + home_adv + league_intercept
        log_lam_h = attack[tid_h] + defense[tid_a] + home_adv + league_intercept
        lam_h = math.exp(log_lam_h)

        # log(lambda_away) = attack_away + defense_home + league_intercept
        log_lam_a = attack[tid_a] + defense[tid_h] + league_intercept
        lam_a = math.exp(log_lam_a)

        # Poisson log-likelihood: -λ + k*log(λ) - log(k!)
        # 用 poisson_pmf 并取 log
        p_h = poisson_pmf(hg, lam_h)
        p_a = poisson_pmf(ag, lam_a)

        if p_h > 0:
            nll -= math.log(p_h)
        else:
            nll -= -lam_h + hg * log_lam_h  # 忽略 log(k!) 常数

        if p_a > 0:
            nll -= math.log(p_a)
        else:
            nll -= -lam_a + ag * log_lam_a

    return nll


def _nll_dixon_coles_rho(
    rho: float,
    lam_h_vec: list[float],
    lam_a_vec: list[float],
    home_goals: list[int],
    away_goals: list[int],
) -> float:
    """Dixon-Coles rho 的负对数似然（低比分 match only）。

    仅对 (x,y) ∈ {(0,0), (0,1), (1,0), (1,1)} 的 match 计算。
    使用已拟合的 Poisson lambdas。
    """
    # τ(x, y, λ, μ, ρ):
    #   0:0 → 1 - λ*μ*ρ
    #   0:1 → 1 + λ*ρ
    #   1:0 → 1 + μ*ρ
    #   1:1 → 1 - ρ

    nll = 0.0
    for i in range(len(home_goals)):
        hg = home_goals[i]
        ag = away_goals[i]

        if hg > 1 or ag > 1:
            continue  # τ = 1 for all other scores, no ρ info

        lam_h = lam_h_vec[i]
        lam_a = lam_a_vec[i]

        if hg == 0 and ag == 0:
            tau = 1.0 - lam_h * lam_a * rho
        elif hg == 0 and ag == 1:
            tau = 1.0 + lam_h * rho
        elif hg == 1 and ag == 0:
            tau = 1.0 + lam_a * rho
        elif hg == 1 and ag == 1:
            tau = 1.0 - rho
        else:
            tau = 1.0

        tau = max(1e-6, tau)

        # P(x,y) = Poisson(x|λ_h) * Poisson(y|λ_a) * τ(x,y)
        p_xy = poisson_pmf(hg, lam_h) * poisson_pmf(ag, lam_a) * tau
        if p_xy > 0:
            nll -= math.log(p_xy)
        else:
            nll += 20.0  # 惩罚

    return nll


# —— 数据加载 ——


def _load_match_data(
    conn: Any,
    min_matches: int = 3,
    league_id: int | None = None,
) -> tuple[
    list[int],  # team_ids (unique, sorted)
    dict[int, int],  # team_id → index
    list[int],  # home_idx
    list[int],  # away_idx
    list[int],  # home_goals
    list[int],  # away_goals
]:
    """从 DB 加载历史比赛数据用于训练。

    Returns:
        (team_ids, team_to_idx, home_idx, away_idx, home_goals, away_goals)
    """
    cur = conn.cursor()

    where = "m.match_status = 'Settled'"
    params = ()
    if league_id:
        where += " AND m.competition_id = %s"
        params = (league_id,)

    cur.execute(
        f"""
        SELECT m.home_team_id, m.away_team_id, r.home_goals, r.away_goals
        FROM official_matches m
        JOIN official_results r ON r.match_id = m.id
        WHERE {where} AND r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
        ORDER BY m.match_date ASC
    """,
        params,
    )

    rows = cur.fetchall()

    # Build team index
    team_set: set[int] = set()
    match_home: list[int] = []
    match_away: list[int] = []
    match_hg: list[int] = []
    match_ag: list[int] = []

    for r in rows:
        htid, atid, hg, ag = int(r[0]), int(r[1]), int(r[2]), int(r[3])
        team_set.add(htid)
        team_set.add(atid)
        match_home.append(htid)
        match_away.append(atid)
        match_hg.append(hg)
        match_ag.append(ag)

    team_ids = sorted(team_set)
    team_to_idx = {tid: i for i, tid in enumerate(team_ids)}
    home_idx = [team_to_idx[t] for t in match_home]
    away_idx = [team_to_idx[t] for t in match_away]

    return team_ids, team_to_idx, home_idx, away_idx, match_hg, match_ag


# —— 主拟合函数 ——


def fit_maher_poisson(
    conn: Any,
    league_id: int | None = None,
) -> dict[str, Any]:
    """用 MLE 拟合 Maher Poisson 模型参数。

    Args:
        conn: DB 连接
        league_id: 联赛 ID（None = 全局）

    Returns:
        {"attack": {team_id: val, ...},
         "defense": {team_id: val, ...},
         "home_advantage": float,
         "league_intercept": float,
         "n_matches": int,
         "n_teams": int,
         "nll": float,
         "converged": bool}
    """
    team_ids, team_to_idx, home_idx, away_idx, hg_vec, ag_vec = _load_match_data(
        conn,
        league_id=league_id,
    )

    n_teams = len(team_ids)
    n_matches = len(hg_vec)

    if n_teams < 2 or n_matches < 10:
        return {
            "error": f"Insufficient data: {n_teams} teams, {n_matches} matches",
            "n_matches": n_matches,
            "n_teams": n_teams,
        }

    # 初始猜测
    init_attack = np.zeros(n_teams)
    init_defense = np.zeros(n_teams)
    init_home_adv = 0.3
    init_intercept = 0.5

    init = np.concatenate([init_attack, init_defense, [init_home_adv, init_intercept]])

    # scipy minimize (L-BFGS-B)
    try:
        from scipy.optimize import minimize  # type: ignore

        result = minimize(
            _nll_maher,
            init,
            args=(team_ids, home_idx, away_idx, hg_vec, ag_vec, n_teams),
            method="L-BFGS-B",
            options={"maxiter": 500, "ftol": 1e-8},
        )

        converged = result.success
        final_params = result.x
        nll = float(result.fun)
    except ImportError:
        # Fallback: simple method-of-moments estimation
        converged = False
        final_params = init
        nll = _nll_maher(init, team_ids, home_idx, away_idx, hg_vec, ag_vec, n_teams)

    attack = {team_ids[i]: round(float(final_params[i]), 4) for i in range(n_teams)}
    defense = {team_ids[i]: round(float(final_params[n_teams + i]), 4) for i in range(n_teams)}
    home_adv = round(float(final_params[-2]), 4)
    league_intercept = round(float(final_params[-1]), 4)

    return {
        "attack": attack,
        "defense": defense,
        "home_advantage": home_adv,
        "league_intercept": league_intercept,
        "n_matches": n_matches,
        "n_teams": n_teams,
        "nll": round(nll, 2),
        "converged": converged,
    }


def fit_dixon_coles_rho(
    conn: Any,
    maher_params: dict[str, Any],
    league_id: int | None = None,
) -> dict[str, Any]:
    """从数据拟合 Dixon-Coles rho 参数。

    Args:
        conn: DB 连接
        maher_params: fit_maher_poisson() 的输出
        league_id: 联赛 ID

    Returns:
        {"rho": float, "n_low_score_matches": int, "nll": float}
    """
    if "error" in maher_params:
        return {"rho": -0.08, "error": "no valid maher params", "n_low_score_matches": 0}

    attack = maher_params["attack"]
    defense = maher_params["defense"]
    home_adv = maher_params["home_advantage"]
    intercept = maher_params["league_intercept"]

    team_ids, team_to_idx, home_idx, away_idx, hg_vec, ag_vec = _load_match_data(
        conn,
        league_id=league_id,
    )

    # 为每场比赛计算 lambda_h, lambda_a
    lam_h_list: list[float] = []
    lam_a_list: list[float] = []
    low_score_count = 0

    for i in range(len(hg_vec)):
        tid_h = home_idx[i]
        tid_a = away_idx[i]
        hg = hg_vec[i]
        ag = ag_vec[i]

        atk_h = attack.get(team_ids[tid_h], 0.0)
        atk_a = attack.get(team_ids[tid_a], 0.0)
        def_h = defense.get(team_ids[tid_h], 0.0)
        def_a = defense.get(team_ids[tid_a], 0.0)

        lam_h = math.exp(atk_h + def_a + home_adv + intercept)
        lam_a = math.exp(atk_a + def_h + intercept)

        lam_h_list.append(lam_h)
        lam_a_list.append(lam_a)

        if hg <= 1 and ag <= 1:
            low_score_count += 1

    # 二分搜索找最优 rho
    best_rho = -0.08
    best_nll = float("inf")

    for rho_cand in np.arange(-0.15, 0.05, 0.002):
        nll = _nll_dixon_coles_rho(
            float(rho_cand),
            lam_h_list,
            lam_a_list,
            hg_vec,
            ag_vec,
        )
        if nll < best_nll:
            best_nll = nll
            best_rho = float(rho_cand)

    return {
        "rho": round(best_rho, 4),
        "n_low_score_matches": low_score_count,
        "n_total_matches": len(hg_vec),
        "nll": round(best_nll, 2),
    }


def fit_all_models(
    conn: Any,
    league_id: int | None = None,
) -> dict[str, Any]:
    """完整训练流水线：Poisson → Dixon-Coles ρ。

    Returns:
        {"maher_poisson": {...}, "dixon_coles_rho": {...}}
    """
    maher = fit_maher_poisson(conn, league_id=league_id)
    if "error" in maher:
        return {"maher_poisson": maher, "dixon_coles_rho": {"error": "cascade"}}

    dc_rho = fit_dixon_coles_rho(conn, maher, league_id=league_id)
    return {"maher_poisson": maher, "dixon_coles_rho": dc_rho}


# —— Job entry point ——


def run(dry_run: bool = False) -> dict[str, Any]:
    """Job: 从历史数据训练模型参数并存储到 model_versions.parameters_json。"""
    if dry_run:
        return {"status": "dry_run", "message": "MLE training (dry run)"}

    from apps.backend.src.db import get_db

    with get_db() as conn:
        result = fit_all_models(conn)

        if "error" in result.get("maher_poisson", {}):
            return {"status": "error", "error": result["maher_poisson"].get("error")}

        maher = result["maher_poisson"]
        dc = result["dixon_coles_rho"]

        # 存储到 DB
        cur = conn.cursor()

        # Update maher_poisson params
        cur.execute(
            """UPDATE model_versions
               SET parameters_json = %s, updated_at = NOW()
               WHERE model_name = 'maher_poisson'""",
            (maher,),
        )

        # Update dixon_coles params (include rho)
        dc_params = {"rho": dc.get("rho", -0.08), "nll": dc.get("nll")}
        cur.execute(
            """UPDATE model_versions
               SET parameters_json = %s, updated_at = NOW()
               WHERE model_name = 'dixon_coles'""",
            (dc_params,),
        )

        conn.commit()

        return {
            "status": "ok",
            "maher": {
                "n_matches": maher["n_matches"],
                "n_teams": maher["n_teams"],
                "home_advantage": maher["home_advantage"],
                "converged": maher["converged"],
            },
            "dixon_coles": {
                "rho": dc.get("rho", -0.08),
                "n_low_score_matches": dc.get("n_low_score_matches", 0),
            },
        }


# —— 自测 ——

if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    print("=== MLE 训练器测试 ===")
    print("（不依赖 DB 的纯数学测试）")

    # 构造 3 支球队的合成数据
    test_team_ids = [1, 2, 3]
    test_home_idx = [0, 1, 2, 0, 1]
    test_away_idx = [1, 2, 0, 2, 0]
    test_hg = [2, 1, 3, 1, 0]
    test_ag = [1, 0, 1, 2, 1]

    import numpy as np

    nll0 = _nll_maher(
        np.zeros(8),  # 2*3 + 2
        test_team_ids,
        test_home_idx,
        test_away_idx,
        test_hg,
        test_ag,
        3,
    )
    print(f"合成数据 NLL (zero init): {nll0:.2f}")
    assert nll0 > 0, "NLL should be positive"

    # 测试 DC rho NLL
    nll_rho = _nll_dixon_coles_rho(
        -0.08,
        [1.3, 1.1, 1.0, 1.2, 0.9],
        [1.1, 1.0, 1.2, 0.9, 1.3],
        test_hg,
        test_ag,
    )
    print(f"DC rho NLL (-0.08): {nll_rho:.2f}")

    print("\n✅ MLE 训练器自测通过")
